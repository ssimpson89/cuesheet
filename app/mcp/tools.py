"""MCP Tool definitions for CueSheet"""

import json
import logging
from typing import Any, Dict, List

from .. import database as db

logger = logging.getLogger("uvicorn.error")


def get_all_tools() -> List[Dict[str, Any]]:
    """Return all MCP tool definitions.

    Each entry carries the ``handler`` and ``annotations`` keys used by the
    server; ``annotations`` follows the MCP ToolAnnotations shape so clients
    can flag destructive tools and ask for confirmation.
    """
    return [
        # =================================================================
        # Read Operations (safe, non-destructive)
        # =================================================================
        {
            "name": "list_all_cues",
            "description": "Get all cues with their camera assignments",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
            "annotations": {"readOnlyHint": True, "destructiveHint": False},
            "handler": handle_list_all_cues,
        },
        {
            "name": "get_cue_details",
            "description": "Get detailed information about a specific cue by ID",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "cue_id": {
                        "type": "integer",
                        "description": "The ID of the cue to retrieve",
                    }
                },
                "required": ["cue_id"],
            },
            "annotations": {"readOnlyHint": True, "destructiveHint": False},
            "handler": handle_get_cue_details,
        },
        {
            "name": "get_current_state",
            "description": "Get the current playback state (which cue is active)",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
            "annotations": {"readOnlyHint": True, "destructiveHint": False},
            "handler": handle_get_current_state,
        },
        {
            "name": "list_cameras",
            "description": "List all cameras and their assignment counts",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
            "annotations": {"readOnlyHint": True, "destructiveHint": False},
            "handler": handle_list_cameras,
        },
        # =================================================================
        # Write Operations - Cues
        # =================================================================
        {
            "name": "create_cue",
            "description": "Create a new cue at the end of the sequence",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "line_text": {
                        "type": "string",
                        "description": "The cue line text (e.g., 'ALADDIN: One jump ahead')",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional notes for the cue",
                        "default": "",
                    },
                },
                "required": ["line_text"],
            },
            "annotations": {"readOnlyHint": False, "destructiveHint": False},
            "handler": handle_create_cue,
        },
        {
            "name": "update_cue",
            "description": "Update an existing cue's text or notes",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "cue_id": {"type": "integer", "description": "The ID of the cue to update"},
                    "line_text": {"type": "string", "description": "New cue text"},
                    "notes": {"type": "string", "description": "New notes"},
                },
                "required": ["cue_id"],
            },
            "annotations": {"readOnlyHint": False, "destructiveHint": False},
            "handler": handle_update_cue,
        },
        {
            "name": "delete_cue",
            "description": "Delete a cue (DESTRUCTIVE: renumbers subsequent cues)",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "cue_id": {
                        "type": "integer",
                        "description": "The ID of the cue to delete",
                    }
                },
                "required": ["cue_id"],
            },
            "annotations": {"readOnlyHint": False, "destructiveHint": True},
            "handler": handle_delete_cue,
        },
        # =================================================================
        # Write Operations - Camera Assignments
        # =================================================================
        {
            "name": "add_camera_assignment",
            "description": "Add or update a camera assignment for a cue",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "cue_id": {"type": "integer", "description": "The cue ID"},
                    "camera_number": {
                        "type": "integer",
                        "description": "Camera number (1, 2, 3, etc.)",
                    },
                    "subject": {
                        "type": "string",
                        "description": "What to shoot (e.g., 'ALADDIN', 'Stage Left', 'Ensemble')",
                    },
                    "shot_type": {
                        "type": "string",
                        "description": "How to shoot (e.g., 'Wide', 'Close', 'Follow', 'Medium')",
                        "default": "",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional notes for the camera operator",
                        "default": "",
                    },
                },
                "required": ["cue_id", "camera_number", "subject"],
            },
            "annotations": {"readOnlyHint": False, "destructiveHint": False},
            "handler": handle_add_camera_assignment,
        },
        {
            "name": "delete_camera_assignment",
            "description": "Remove a camera assignment from a cue (DESTRUCTIVE)",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "cue_id": {"type": "integer", "description": "The cue ID"},
                    "camera_number": {
                        "type": "integer",
                        "description": "Camera number to remove",
                    },
                },
                "required": ["cue_id", "camera_number"],
            },
            "annotations": {"readOnlyHint": False, "destructiveHint": True},
            "handler": handle_delete_camera_assignment,
        },
        # =================================================================
        # Utility Operations
        # =================================================================
        {
            "name": "advance_to_cue",
            "description": "Navigate to a specific cue number (changes live playback state)",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "cue_number": {
                        "type": "integer",
                        "description": "The sequence number of the cue to navigate to",
                    }
                },
                "required": ["cue_number"],
            },
            "annotations": {"readOnlyHint": False, "destructiveHint": True},
            "handler": handle_advance_to_cue,
        },
        {
            "name": "export_to_csv",
            "description": "Export all cues and camera assignments to CSV format",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
            "annotations": {"readOnlyHint": True, "destructiveHint": False},
            "handler": handle_export_csv,
        },
    ]


# =================================================================
# Tool Handlers
# =================================================================


async def handle_list_all_cues(arguments: Dict[str, Any]) -> List[Dict[str, Any]]:
    cues = await db.get_all_cues_with_cameras()
    return [{"type": "text", "text": json.dumps(cues, indent=2)}]


async def handle_get_cue_details(arguments: Dict[str, Any]) -> List[Dict[str, Any]]:
    cue_id = arguments["cue_id"]
    all_cues = await db.get_all_cues_with_cameras()
    cue = next((c for c in all_cues if c["id"] == cue_id), None)
    if not cue:
        return [{"type": "text", "text": json.dumps({"error": f"Cue {cue_id} not found"})}]
    return [{"type": "text", "text": json.dumps(cue, indent=2)}]


async def handle_get_current_state(arguments: Dict[str, Any]) -> List[Dict[str, Any]]:
    state = await db.get_current_state()
    return [{"type": "text", "text": json.dumps(state, indent=2)}]


async def handle_list_cameras(arguments: Dict[str, Any]) -> List[Dict[str, Any]]:
    cameras = await db.get_cameras_list()
    return [{"type": "text", "text": json.dumps(cameras, indent=2)}]


async def handle_create_cue(arguments: Dict[str, Any]) -> List[Dict[str, Any]]:
    line_text = arguments["line_text"]
    notes = arguments.get("notes", "")

    next_seq = (await db.get_max_sequence_number(1)) + 1
    cue_id = await db.create_cue_at_position(
        script_id=1, sequence_number=next_seq, line_text=line_text, notes=notes
    )
    return [
        {
            "type": "text",
            "text": json.dumps(
                {
                    "success": True,
                    "cue_id": cue_id,
                    "sequence_number": next_seq,
                    "message": f"Created cue {next_seq} (ID: {cue_id})",
                },
                indent=2,
            ),
        }
    ]


async def handle_update_cue(arguments: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Update a cue, preserving fields the caller didn't supply.

    The tool schema marks line_text/notes as optional; an omitted field must
    not clobber the existing value.
    """
    cue_id = arguments["cue_id"]

    # Look up the existing cue so we can preserve unspecified fields.
    existing = None
    for c in await db.get_all_cues_with_cameras():
        if c["id"] == cue_id:
            existing = c
            break

    if existing is None:
        return [
            {
                "type": "text",
                "text": json.dumps(
                    {"success": False, "message": f"Cue {cue_id} not found"},
                    indent=2,
                ),
            }
        ]

    line_text = arguments["line_text"] if "line_text" in arguments else existing.get("line_text") or ""
    notes = arguments["notes"] if "notes" in arguments else existing.get("notes") or ""

    await db.update_cue(cue_id=cue_id, line_text=line_text, notes=notes)
    return [
        {
            "type": "text",
            "text": json.dumps(
                {"success": True, "cue_id": cue_id, "message": f"Updated cue {cue_id}"},
                indent=2,
            ),
        }
    ]


async def handle_delete_cue(arguments: Dict[str, Any]) -> List[Dict[str, Any]]:
    cue_id = arguments["cue_id"]
    await db.delete_cue(cue_id)
    return [
        {
            "type": "text",
            "text": json.dumps(
                {
                    "success": True,
                    "cue_id": cue_id,
                    "message": f"Deleted cue {cue_id} (subsequent cues renumbered)",
                },
                indent=2,
            ),
        }
    ]


async def handle_add_camera_assignment(arguments: Dict[str, Any]) -> List[Dict[str, Any]]:
    cue_id = arguments["cue_id"]
    camera_number = arguments["camera_number"]
    subject = arguments["subject"]
    shot_type = arguments.get("shot_type", "")
    notes = arguments.get("notes", "")
    await db.update_camera_assignment(
        cue_id=cue_id,
        camera_number=camera_number,
        subject=subject,
        shot_type=shot_type,
        notes=notes,
    )
    return [
        {
            "type": "text",
            "text": json.dumps(
                {
                    "success": True,
                    "cue_id": cue_id,
                    "camera_number": camera_number,
                    "message": f"Added/updated camera {camera_number} for cue {cue_id}",
                },
                indent=2,
            ),
        }
    ]


async def handle_delete_camera_assignment(arguments: Dict[str, Any]) -> List[Dict[str, Any]]:
    cue_id = arguments["cue_id"]
    camera_number = arguments["camera_number"]
    await db.delete_camera_assignment(cue_id=cue_id, camera_number=camera_number)
    return [
        {
            "type": "text",
            "text": json.dumps(
                {
                    "success": True,
                    "cue_id": cue_id,
                    "camera_number": camera_number,
                    "message": f"Deleted camera {camera_number} from cue {cue_id}",
                },
                indent=2,
            ),
        }
    ]


async def handle_advance_to_cue(arguments: Dict[str, Any]) -> List[Dict[str, Any]]:
    cue_number = arguments["cue_number"]
    cue_id = await db.go_to_cue(cue_number)
    if cue_id is None:
        return [
            {
                "type": "text",
                "text": json.dumps(
                    {"success": False, "message": f"Cue {cue_number} not found"},
                    indent=2,
                ),
            }
        ]
    state = await db.get_current_state()
    return [
        {
            "type": "text",
            "text": json.dumps(
                {
                    "success": True,
                    "current_state": state,
                    "message": f"Advanced to cue {cue_number}",
                },
                indent=2,
            ),
        }
    ]


async def handle_export_csv(arguments: Dict[str, Any]) -> List[Dict[str, Any]]:
    csv_content = await db.export_to_csv()
    return [{"type": "text", "text": f"CSV Export:\n\n{csv_content}"}]
