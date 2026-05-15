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
        # Defensive int parse — the admin UI can persist an empty string if
        # the user clears the input. Treat any non-integer value as "no limit".
        raw_limit = await db.get_setting("ai_daily_request_limit", "0")
        try:
            self.daily_limit = int(raw_limit)
        except (TypeError, ValueError):
            self.daily_limit = 0

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

        # Cache cues for resolving model-supplied identifiers to real DB IDs.
        # The prompt instructs the model that "cue 26" = sequence_number 26,
        # so any numeric cue_id/target_cue_id is treated as a sequence number
        # unless it matches a known DB id directly (defensive double-lookup).
        all_cues_cache = await db.get_all_cues_with_cameras()
        cues_by_id = {c["id"]: c for c in all_cues_cache}
        cues_by_seq = {c["sequence_number"]: c for c in all_cues_cache}

        def resolve_cue_id(ref):
            """Resolve a model-supplied cue reference to a DB id.

            Accepts the `$LAST_CREATED_CUE` sentinel, an int that may be a
            sequence_number (preferred per prompt) or a DB id (fallback), or
            returns None if no match. Re-fetches the cache after mutations
            so $LAST_CREATED_CUE and subsequent references stay valid.
            """
            if ref == "$LAST_CREATED_CUE":
                return last_created_cue_id
            if ref is None:
                return None
            # Prefer sequence_number per prompt rule 5
            if ref in cues_by_seq:
                return cues_by_seq[ref]["id"]
            # Fall back to direct DB id match
            if ref in cues_by_id:
                return cues_by_id[ref]["id"]
            return None

        for op in operations:
            op_type = op.get("type")
            params = op.get("params", {})

            try:
                if op_type == "create_cue":
                    position = params.get("position", "end")
                    target_db_id = resolve_cue_id(params.get("target_cue_id"))

                    if position == "start":
                        sequence_number = 1
                    elif position == "end":
                        sequence_number = len(all_cues_cache) + 1
                    elif position in ("before", "after") and target_db_id is not None:
                        target_cue = cues_by_id.get(target_db_id)
                        if target_cue is None:
                            sequence_number = len(all_cues_cache) + 1
                        elif position == "before":
                            sequence_number = target_cue["sequence_number"]
                        else:
                            sequence_number = target_cue["sequence_number"] + 1
                    else:
                        sequence_number = len(all_cues_cache) + 1

                    cue_id = await db.create_cue_at_position(
                        script_id=1,
                        sequence_number=sequence_number,
                        line_text=params["line_text"],
                        notes=params.get("notes", ""),
                    )
                    last_created_cue_id = cue_id
                    # Refresh caches so subsequent ops see the new cue and the
                    # renumbered neighbours.
                    all_cues_cache = await db.get_all_cues_with_cameras()
                    cues_by_id = {c["id"]: c for c in all_cues_cache}
                    cues_by_seq = {c["sequence_number"]: c for c in all_cues_cache}
                    results.append({"type": op_type, "cue_id": cue_id, "success": True})

                elif op_type == "update_cue":
                    db_id = resolve_cue_id(params.get("cue_id"))
                    if db_id is None:
                        errors.append(f"update_cue: cue {params.get('cue_id')} not found")
                        results.append({"type": op_type, "success": False, "error": "not found"})
                        continue
                    # Preserve fields the model didn't provide — explicitly
                    # omitted keys must not blank out existing values.
                    existing = cues_by_id.get(db_id, {})
                    line_text = params["line_text"] if "line_text" in params else existing.get("line_text", "")
                    notes = params["notes"] if "notes" in params else existing.get("notes", "")
                    await db.update_cue(cue_id=db_id, line_text=line_text or "", notes=notes or "")
                    results.append({"type": op_type, "cue_id": db_id, "success": True})

                elif op_type == "delete_cue":
                    db_id = resolve_cue_id(params.get("cue_id"))
                    if db_id is None:
                        errors.append(f"delete_cue: cue {params.get('cue_id')} not found")
                        results.append({"type": op_type, "success": False, "error": "not found"})
                        continue
                    await db.delete_cue(db_id)
                    # Refresh after delete since sequence numbers shift.
                    all_cues_cache = await db.get_all_cues_with_cameras()
                    cues_by_id = {c["id"]: c for c in all_cues_cache}
                    cues_by_seq = {c["sequence_number"]: c for c in all_cues_cache}
                    results.append({"type": op_type, "cue_id": db_id, "success": True})

                elif op_type == "add_camera":
                    db_id = resolve_cue_id(params.get("cue_id"))
                    if db_id is None:
                        errors.append(f"add_camera: cue {params.get('cue_id')} not found")
                        results.append({"type": op_type, "success": False, "error": "not found"})
                        continue
                    await db.update_camera_assignment(
                        cue_id=db_id,
                        camera_number=params["camera_number"],
                        subject=params["subject"],
                        shot_type=params.get("shot_type", ""),
                        notes=params.get("notes", ""),
                    )
                    results.append(
                        {
                            "type": op_type,
                            "cue_id": db_id,
                            "camera_number": params["camera_number"],
                            "success": True,
                        }
                    )

                elif op_type == "update_camera":
                    db_id = resolve_cue_id(params.get("cue_id"))
                    if db_id is None:
                        errors.append(f"update_camera: cue {params.get('cue_id')} not found")
                        results.append({"type": op_type, "success": False, "error": "not found"})
                        continue
                    # Preserve fields the model didn't supply.
                    cue = cues_by_id.get(db_id, {})
                    cam_num = params["camera_number"]
                    existing_cam = next(
                        (c for c in (cue.get("cameras") or []) if c["camera_number"] == cam_num),
                        {},
                    )
                    subject = params["subject"] if "subject" in params else existing_cam.get("subject", "")
                    shot_type = params["shot_type"] if "shot_type" in params else existing_cam.get("shot_type", "")
                    notes = params["notes"] if "notes" in params else existing_cam.get("notes", "")
                    await db.update_camera_assignment(
                        cue_id=db_id,
                        camera_number=cam_num,
                        subject=subject or "",
                        shot_type=shot_type or "",
                        notes=notes or "",
                    )
                    results.append(
                        {
                            "type": op_type,
                            "cue_id": db_id,
                            "camera_number": cam_num,
                            "success": True,
                        }
                    )

                elif op_type == "delete_camera":
                    db_id = resolve_cue_id(params.get("cue_id"))
                    if db_id is None:
                        errors.append(f"delete_camera: cue {params.get('cue_id')} not found")
                        results.append({"type": op_type, "success": False, "error": "not found"})
                        continue
                    await db.delete_camera_assignment(
                        cue_id=db_id, camera_number=params["camera_number"]
                    )
                    results.append(
                        {
                            "type": op_type,
                            "cue_id": db_id,
                            "camera_number": params["camera_number"],
                            "success": True,
                        }
                    )

                elif op_type == "bulk_add_cameras":
                    db_id = resolve_cue_id(params.get("cue_id"))
                    if db_id is None:
                        errors.append(f"bulk_add_cameras: cue {params.get('cue_id')} not found")
                        results.append({"type": op_type, "success": False, "error": "not found"})
                        continue

                    cameras = params.get("cameras", []) or []
                    for cam in cameras:
                        cam_num = cam.get("camera_number")
                        if cam_num is None:
                            continue
                        await db.update_camera_assignment(
                            cue_id=db_id,
                            camera_number=cam_num,
                            subject=cam.get("subject", ""),
                            shot_type=cam.get("shot_type", ""),
                            notes=cam.get("notes", ""),
                        )

                    results.append(
                        {
                            "type": op_type,
                            "cue_id": db_id,
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
