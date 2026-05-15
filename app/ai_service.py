"""AI service for natural language command parsing and execution"""

import os
import json
import logging
from datetime import datetime
from typing import Optional, Dict, List, Any
from openai import AsyncOpenAI
from dotenv import load_dotenv

from . import database as db
from . import ai_prompts

# Load environment variables
load_dotenv()

logger = logging.getLogger("uvicorn.error")


class AIService:
    """Core AI integration service for CueSheet"""

    def __init__(self):
        """Initialize AI service with configuration"""
        self.api_key = os.getenv("OPENROUTER_API_KEY")
        self.base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        self.client = None

        # Will be loaded from database
        self.enabled = False
        self.model = "openai/gpt-4o-mini"
        self.daily_limit = 0

    async def _init_from_db(self):
        """Load configuration from database settings"""
        self.enabled = await db.get_setting("ai_enabled", "false") == "true"
        self.model = await db.get_setting("ai_model", "openai/gpt-4o-mini")
        self.daily_limit = int(await db.get_setting("ai_daily_request_limit", "0"))

        # Initialize OpenAI client if API key is available
        if self.api_key and self.api_key != "sk-or-v1-your-key-here":
            self.client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)

    async def is_available(self) -> bool:
        """Check if AI service is available and configured"""
        await self._init_from_db()

        if not self.api_key or self.api_key == "sk-or-v1-your-key-here":
            return False

        if not self.enabled:
            return False

        return True

    async def parse_command(
        self, user_message: str, context: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Parse natural language command into structured operations

        Args:
            user_message: User's natural language command
            context: Current app state (current_cue_id, script_name, etc.)

        Returns:
            {
                "operations": [...],
                "confirmation_message": "...",
                "preview": true/false,
                "error": "..." (if failed)
            }
        """
        if not await self.is_available():
            return {
                "error": "AI Assistant is not available. Please configure API key in admin settings."
            }

        try:
            # Build the full prompt with context
            system_prompt = ai_prompts.SYSTEM_PROMPT
            user_prompt = f"User Command: {user_message}\n\n"

            if context:
                user_prompt += f"Current Context: {json.dumps(context, indent=2)}\n\n"

            user_prompt += (
                "Return your response as valid JSON only, no additional text."
            )

            # Call OpenRouter API
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,  # Low temperature for consistent parsing
                max_tokens=2000,
            )

            # Parse AI response
            ai_response = response.choices[0].message.content.strip()

            # Extract JSON from response (in case AI adds markdown formatting)
            if "```json" in ai_response:
                ai_response = ai_response.split("```json")[1].split("```")[0].strip()
            elif "```" in ai_response:
                ai_response = ai_response.split("```")[1].split("```")[0].strip()

            result = json.loads(ai_response)

            # Validate response structure
            if "operations" not in result:
                return {"error": "Invalid AI response: missing 'operations' field"}

            if "confirmation_message" not in result:
                result["confirmation_message"] = "Operation ready to execute."

            if "preview" not in result:
                result["preview"] = False

            return result

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI response as JSON: {e}")
            return {"error": f"AI returned invalid JSON: {str(e)}"}
        except Exception as e:
            logger.error(f"AI service error: {e}")
            return {"error": f"AI service error: {str(e)}"}

    async def parse_script_bulk(self, script_text: str) -> Dict[str, Any]:
        """
        Parse entire script and extract cues with camera suggestions

        Args:
            script_text: Full script text to parse

        Returns:
            {
                "cues": [...],
                "metadata": {...},
                "error": "..." (if failed)
            }
        """
        if not await self.is_available():
            return {
                "error": "AI Assistant is not available. Please configure API key in admin settings."
            }

        try:
            # Call OpenRouter API with bulk import prompt
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": ai_prompts.BULK_IMPORT_PROMPT},
                    {
                        "role": "user",
                        "content": f"Script:\n\n{script_text}\n\nReturn your response as valid JSON only.",
                    },
                ],
                temperature=0.2,
                max_tokens=4000,  # Longer for bulk import
            )

            # Parse AI response
            ai_response = response.choices[0].message.content.strip()

            # Extract JSON from response
            if "```json" in ai_response:
                ai_response = ai_response.split("```json")[1].split("```")[0].strip()
            elif "```" in ai_response:
                ai_response = ai_response.split("```")[1].split("```")[0].strip()

            result = json.loads(ai_response)

            # Validate response structure
            if "cues" not in result:
                return {"error": "Invalid AI response: missing 'cues' field"}

            return result

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI bulk import response: {e}")
            return {"error": f"AI returned invalid JSON: {str(e)}"}
        except Exception as e:
            logger.error(f"AI bulk import error: {e}")
            return {"error": f"AI bulk import error: {str(e)}"}

    async def execute_operations(
        self, operations: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Execute a list of operations against the database

        Args:
            operations: List of operations to execute

        Returns:
            {
                "success": true/false,
                "results": [...],
                "summary": "..."
            }
        """
        results = []
        errors = []
        last_created_cue_id = None  # Track the most recently created cue

        for op in operations:
            op_type = op.get("type")
            params = op.get("params", {})

            try:
                if op_type == "create_cue":
                    # Convert position-based parameters to sequence_number
                    position = params.get("position", "end")
                    target_cue_id = params.get("target_cue_id")

                    # Get all cues to determine sequence number
                    all_cues = await db.get_all_cues_with_cameras()

                    if position == "start":
                        sequence_number = 1
                    elif position == "end":
                        sequence_number = len(all_cues) + 1
                    elif position == "before" and target_cue_id:
                        target_cue = next(
                            (c for c in all_cues if c["id"] == target_cue_id), None
                        )
                        sequence_number = (
                            target_cue["sequence_number"]
                            if target_cue
                            else len(all_cues) + 1
                        )
                    elif position == "after" and target_cue_id:
                        target_cue = next(
                            (c for c in all_cues if c["id"] == target_cue_id), None
                        )
                        sequence_number = (
                            target_cue["sequence_number"] + 1
                            if target_cue
                            else len(all_cues) + 1
                        )
                    else:
                        sequence_number = len(all_cues) + 1

                    cue_id = await db.create_cue_at_position(
                        script_id=1,
                        sequence_number=sequence_number,
                        line_text=params["line_text"],
                        notes=params.get("notes", ""),
                    )
                    last_created_cue_id = cue_id  # Track for subsequent operations
                    results.append({"type": op_type, "cue_id": cue_id, "success": True})

                elif op_type == "update_cue":
                    await db.update_cue(
                        cue_id=params["cue_id"],
                        line_text=params.get("line_text"),
                        notes=params.get("notes"),
                    )
                    results.append(
                        {"type": op_type, "cue_id": params["cue_id"], "success": True}
                    )

                elif op_type == "delete_cue":
                    await db.delete_cue(params["cue_id"])
                    results.append(
                        {"type": op_type, "cue_id": params["cue_id"], "success": True}
                    )

                elif op_type == "add_camera":
                    # Replace $LAST_CREATED_CUE marker with actual cue_id
                    cue_id = params["cue_id"]
                    if cue_id == "$LAST_CREATED_CUE" and last_created_cue_id:
                        cue_id = last_created_cue_id

                    await db.update_camera_assignment(
                        cue_id=cue_id,
                        camera_number=params["camera_number"],
                        subject=params["subject"],
                        shot_type=params.get("shot_type", ""),
                        notes=params.get("notes", ""),
                    )
                    results.append(
                        {
                            "type": op_type,
                            "cue_id": cue_id,
                            "camera_number": params["camera_number"],
                            "success": True,
                        }
                    )

                elif op_type == "update_camera":
                    await db.update_camera_assignment(
                        cue_id=params["cue_id"],
                        camera_number=params["camera_number"],
                        subject=params.get("subject"),
                        shot_type=params.get("shot_type"),
                        notes=params.get("notes"),
                    )
                    results.append(
                        {
                            "type": op_type,
                            "cue_id": params["cue_id"],
                            "camera_number": params["camera_number"],
                            "success": True,
                        }
                    )

                elif op_type == "delete_camera":
                    await db.delete_camera_assignment(
                        cue_id=params["cue_id"], camera_number=params["camera_number"]
                    )
                    results.append(
                        {
                            "type": op_type,
                            "cue_id": params["cue_id"],
                            "camera_number": params["camera_number"],
                            "success": True,
                        }
                    )

                elif op_type == "bulk_add_cameras":
                    # Replace $LAST_CREATED_CUE marker with actual cue_id
                    cue_id = params["cue_id"]
                    if cue_id == "$LAST_CREATED_CUE" and last_created_cue_id:
                        cue_id = last_created_cue_id

                    cameras = params.get("cameras", [])

                    for cam in cameras:
                        await db.update_camera_assignment(
                            cue_id=cue_id,
                            camera_number=cam["camera_number"],
                            subject=cam.get("subject", ""),
                            shot_type=cam.get("shot_type", ""),
                            notes=cam.get("notes", ""),
                        )

                    results.append(
                        {
                            "type": op_type,
                            "cue_id": cue_id,
                            "camera_count": len(cameras),
                            "success": True,
                        }
                    )

                else:
                    errors.append(f"Unknown operation type: {op_type}")

            except Exception as e:
                logger.error(f"Error executing operation {op_type}: {e}")
                errors.append(f"{op_type}: {str(e)}")
                results.append({"type": op_type, "success": False, "error": str(e)})

        # Build summary
        success_count = sum(1 for r in results if r.get("success"))
        summary_parts = []

        if success_count > 0:
            summary_parts.append(
                f"✅ Successfully completed {success_count} operation(s)"
            )

        if errors:
            summary_parts.append(f"❌ {len(errors)} error(s): {'; '.join(errors)}")

        summary = (
            ". ".join(summary_parts) if summary_parts else "No operations executed"
        )

        return {"success": len(errors) == 0, "results": results, "summary": summary}

    async def check_usage_limits(self) -> Dict[str, Any]:
        """
        Check if usage is within configured limits

        Returns:
            {
                "allowed": true/false,
                "count_today": 42,
                "limit": 100,
                "reset_at": "2026-01-20T00:00:00Z"
            }
        """
        await self._init_from_db()

        # Get today's usage count
        count_today = await self._get_usage_today()

        # Check if limit is set (0 = unlimited)
        allowed = True
        if self.daily_limit > 0 and count_today >= self.daily_limit:
            allowed = False

        # Calculate reset time (midnight tonight)
        now = datetime.now()
        reset_at = now.replace(hour=23, minute=59, second=59, microsecond=999999)

        return {
            "allowed": allowed,
            "count_today": count_today,
            "limit": self.daily_limit,
            "reset_at": reset_at.isoformat(),
        }

    async def increment_usage(self):
        """Increment today's usage counter"""
        today = datetime.now().strftime("%Y-%m-%d")
        key = f"ai_usage_count_{today}"

        current = await db.get_setting(key, "0")
        await db.set_setting(key, str(int(current) + 1))

        # Update last reset date
        await db.set_setting("ai_last_reset_date", today)

    async def _get_usage_today(self) -> int:
        """Get today's usage count"""
        today = datetime.now().strftime("%Y-%m-%d")
        key = f"ai_usage_count_{today}"
        return int(await db.get_setting(key, "0"))
