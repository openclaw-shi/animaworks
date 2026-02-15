from __future__ import annotations
# AnimaWorks - Digital Person Framework
# Copyright (C) 2026 AnimaWorks Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of AnimaWorks core/server, licensed under AGPL-3.0.
# See LICENSES/AGPL-3.0.txt for the full license text.


"""External tool dispatcher.

Maps tool schema names to the appropriate module function/class method call.
Each external tool module (web_search, slack, chatwork, ...) is loaded
dynamically and executed here.
"""

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger("animaworks.external_tools")


# ── Handler functions ────────────────────────────────────────
#
# Each handler takes (mod, args) and returns the raw result value.
# They are referenced by the _DISPATCH_TABLE dict at the bottom.


def _handle_web_search(mod: Any, args: dict[str, Any]) -> Any:
    """Handle ``web_search`` schema."""
    return mod.search(**args)


def _handle_x_search(mod: Any, args: dict[str, Any]) -> Any:
    """Handle ``x_search`` schema."""
    client = mod.XSearchClient()
    return client.search_recent(
        query=args["query"],
        max_results=args.get("max_results", 10),
        days=args.get("days", 7),
    )


def _handle_x_user_tweets(mod: Any, args: dict[str, Any]) -> Any:
    """Handle ``x_user_tweets`` schema."""
    client = mod.XSearchClient()
    return client.get_user_tweets(
        username=args["username"],
        max_results=args.get("max_results", 10),
        days=args.get("days"),
    )


def _handle_chatwork_send(mod: Any, args: dict[str, Any]) -> Any:
    """Handle ``chatwork_send`` schema."""
    client = mod.ChatworkClient()
    room_id = client.resolve_room_id(args["room"])
    return client.post_message(room_id, args["message"])


def _handle_chatwork_messages(mod: Any, args: dict[str, Any]) -> Any:
    """Handle ``chatwork_messages`` schema."""
    client = mod.ChatworkClient()
    room_id = client.resolve_room_id(args["room"])
    cache = mod.MessageCache()
    try:
        msgs = client.get_messages(room_id, force=True)
        if msgs:
            cache.upsert_messages(room_id, msgs)
            cache.update_sync_state(room_id)
        return cache.get_recent(room_id, limit=args.get("limit", 20))
    finally:
        cache.close()


def _handle_chatwork_search(mod: Any, args: dict[str, Any]) -> Any:
    """Handle ``chatwork_search`` schema."""
    client = mod.ChatworkClient()
    cache = mod.MessageCache()
    try:
        room_id = None
        if args.get("room"):
            room_id = client.resolve_room_id(args["room"])
        return cache.search(
            args["keyword"], room_id=room_id, limit=args.get("limit", 50),
        )
    finally:
        cache.close()


def _handle_chatwork_unreplied(mod: Any, args: dict[str, Any]) -> Any:
    """Handle ``chatwork_unreplied`` schema."""
    client = mod.ChatworkClient()
    cache = mod.MessageCache()
    try:
        my_info = client.me()
        my_id = str(my_info["account_id"])
        return cache.find_unreplied(
            my_id, exclude_toall=not args.get("include_toall", False),
        )
    finally:
        cache.close()


def _handle_chatwork_rooms(mod: Any, args: dict[str, Any]) -> Any:
    """Handle ``chatwork_rooms`` schema."""
    client = mod.ChatworkClient()
    return client.rooms()


def _handle_slack_send(mod: Any, args: dict[str, Any]) -> Any:
    """Handle ``slack_send`` schema."""
    client = mod.SlackClient()
    channel_id = client.resolve_channel(args["channel"])
    return client.post_message(
        channel_id,
        args["message"],
        thread_ts=args.get("thread_ts"),
    )


def _handle_slack_messages(mod: Any, args: dict[str, Any]) -> Any:
    """Handle ``slack_messages`` schema."""
    client = mod.SlackClient()
    channel_id = client.resolve_channel(args["channel"])
    cache = mod.MessageCache()
    try:
        limit = args.get("limit", 20)
        msgs = client.channel_history(channel_id, limit=limit)
        if msgs:
            for m in msgs:
                uid = m.get("user", m.get("bot_id", ""))
                if uid:
                    m["user_name"] = client.resolve_user_name(uid)
            cache.upsert_messages(channel_id, msgs)
            cache.update_sync_state(channel_id)
        return cache.get_recent(channel_id, limit=limit)
    finally:
        cache.close()


def _handle_slack_search(mod: Any, args: dict[str, Any]) -> Any:
    """Handle ``slack_search`` schema."""
    client = mod.SlackClient()
    cache = mod.MessageCache()
    try:
        channel_id = None
        if args.get("channel"):
            channel_id = client.resolve_channel(args["channel"])
        return cache.search(
            args["keyword"], channel_id=channel_id, limit=args.get("limit", 50),
        )
    finally:
        cache.close()


def _handle_slack_unreplied(mod: Any, args: dict[str, Any]) -> Any:
    """Handle ``slack_unreplied`` schema."""
    client = mod.SlackClient()
    cache = mod.MessageCache()
    try:
        client.auth_test()
        return cache.find_unreplied(client.my_user_id)
    finally:
        cache.close()


def _handle_slack_channels(mod: Any, args: dict[str, Any]) -> Any:
    """Handle ``slack_channels`` schema."""
    client = mod.SlackClient()
    return client.channels()


def _handle_gmail_unread(mod: Any, args: dict[str, Any]) -> Any:
    """Handle ``gmail_unread`` schema."""
    client = mod.GmailClient()
    emails = client.get_unread_emails(max_results=args.get("max_results", 20))
    return [
        {"id": e.id, "from": e.from_addr, "subject": e.subject, "snippet": e.snippet}
        for e in emails
    ]


def _handle_gmail_read_body(mod: Any, args: dict[str, Any]) -> Any:
    """Handle ``gmail_read_body`` schema."""
    client = mod.GmailClient()
    return client.get_email_body(args["message_id"])


def _handle_gmail_draft(mod: Any, args: dict[str, Any]) -> Any:
    """Handle ``gmail_draft`` schema."""
    client = mod.GmailClient()
    result = client.create_draft(
        to=args["to"],
        subject=args["subject"],
        body=args["body"],
        thread_id=args.get("thread_id"),
        in_reply_to=args.get("in_reply_to"),
    )
    return {"success": result.success, "draft_id": result.draft_id, "error": result.error}


def _handle_local_llm_generate(mod: Any, args: dict[str, Any]) -> Any:
    """Handle ``local_llm_generate`` schema."""
    client = mod.OllamaClient(
        server=args.get("server", "auto"),
        model=args.get("model"),
        hint=args.get("hint"),
    )
    return client.generate(
        prompt=args["prompt"],
        system=args.get("system", ""),
        temperature=args.get("temperature", 0.7),
        max_tokens=args.get("max_tokens", 4096),
        think=args.get("think", "off"),
    )


def _handle_local_llm_chat(mod: Any, args: dict[str, Any]) -> Any:
    """Handle ``local_llm_chat`` schema."""
    client = mod.OllamaClient(
        server=args.get("server", "auto"),
        model=args.get("model"),
        hint=args.get("hint"),
    )
    return client.chat(
        messages=args["messages"],
        system=args.get("system", ""),
        temperature=args.get("temperature", 0.7),
        max_tokens=args.get("max_tokens", 4096),
        think=args.get("think", "off"),
    )


def _handle_local_llm_models(mod: Any, args: dict[str, Any]) -> Any:
    """Handle ``local_llm_models`` schema."""
    client = mod.OllamaClient(server=args.get("server", "auto"))
    return client.list_models()


def _handle_local_llm_status(mod: Any, args: dict[str, Any]) -> Any:
    """Handle ``local_llm_status`` schema."""
    client = mod.OllamaClient()
    return client.server_status()


def _handle_transcribe_audio(mod: Any, args: dict[str, Any]) -> Any:
    """Handle ``transcribe_audio`` schema."""
    return mod.process_audio(
        audio_path=args["audio_path"],
        language=args.get("language"),
        model=args.get("model"),
        raw_only=args.get("raw_only", False),
        custom_prompt=args.get("custom_prompt"),
    )


def _handle_aws_ecs_status(mod: Any, args: dict[str, Any]) -> Any:
    """Handle ``aws_ecs_status`` schema."""
    collector = mod.AWSCollector(region=args.get("region"))
    return collector.get_ecs_status(args["cluster"], args["service"])


def _handle_aws_error_logs(mod: Any, args: dict[str, Any]) -> Any:
    """Handle ``aws_error_logs`` schema."""
    collector = mod.AWSCollector(region=args.get("region"))
    return collector.get_error_logs(
        log_group=args["log_group"],
        hours=args.get("hours", 1),
        patterns=args.get("patterns"),
    )


def _handle_aws_metrics(mod: Any, args: dict[str, Any]) -> Any:
    """Handle ``aws_metrics`` schema."""
    collector = mod.AWSCollector(region=args.get("region"))
    return collector.get_metrics(
        cluster=args["cluster"],
        service=args["service"],
        metric=args.get("metric", "CPUUtilization"),
        hours=args.get("hours", 1),
    )


def _handle_github_list_issues(mod: Any, args: dict[str, Any]) -> Any:
    """Handle ``github_list_issues`` schema."""
    client = mod.GitHubClient(repo=args.get("repo"))
    return client.list_issues(
        state=args.get("state", "open"),
        labels=args.get("labels"),
        limit=args.get("limit", 20),
    )


def _handle_github_create_issue(mod: Any, args: dict[str, Any]) -> Any:
    """Handle ``github_create_issue`` schema."""
    client = mod.GitHubClient(repo=args.get("repo"))
    return client.create_issue(
        title=args["title"],
        body=args.get("body", ""),
        labels=args.get("labels"),
    )


def _handle_github_list_prs(mod: Any, args: dict[str, Any]) -> Any:
    """Handle ``github_list_prs`` schema."""
    client = mod.GitHubClient(repo=args.get("repo"))
    return client.list_prs(
        state=args.get("state", "open"),
        limit=args.get("limit", 20),
    )


def _handle_github_create_pr(mod: Any, args: dict[str, Any]) -> Any:
    """Handle ``github_create_pr`` schema."""
    client = mod.GitHubClient(repo=args.get("repo"))
    return client.create_pr(
        title=args["title"],
        body=args.get("body", ""),
        head=args["head"],
        base=args.get("base", "main"),
        draft=args.get("draft", False),
    )


def _handle_generate_character_assets(mod: Any, args: dict[str, Any]) -> Any:
    """Handle ``generate_character_assets`` schema."""
    from core.config.models import load_config
    from core.paths import get_persons_dir

    person_dir = Path(args.pop("person_dir", ""))
    supervisor_name: str | None = args.pop("supervisor_name", None)
    config = load_config()
    image_config = config.image_gen

    # Use supervisor's fullbody image as Vibe Transfer reference
    if supervisor_name:
        supervisor_fullbody = (
            get_persons_dir() / supervisor_name / "assets" / "avatar_fullbody.png"
        )
        if supervisor_fullbody.exists():
            image_config = image_config.model_copy(
                update={"style_reference": str(supervisor_fullbody)},
            )
            logger.info(
                "Using supervisor image as vibe reference: %s",
                supervisor_fullbody,
            )

    pipeline = mod.ImageGenPipeline(person_dir, config=image_config)
    result = pipeline.generate_all(
        prompt=args["prompt"],
        negative_prompt=args.get("negative_prompt", ""),
        skip_existing=args.get("skip_existing", True),
        steps=args.get("steps"),
        animations=args.get("animations"),
    )
    return result.to_dict()


def _handle_generate_fullbody(mod: Any, args: dict[str, Any]) -> Any:
    """Handle ``generate_fullbody`` schema."""
    person_dir = Path(args.pop("person_dir", ""))
    assets_dir = person_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    client = mod.NovelAIClient()
    img = client.generate_fullbody(
        prompt=args["prompt"],
        negative_prompt=args.get("negative_prompt", ""),
        width=args.get("width", 1024),
        height=args.get("height", 1536),
        seed=args.get("seed"),
    )
    out = assets_dir / "avatar_fullbody.png"
    out.write_bytes(img)
    return {"path": str(out), "size": len(img)}


def _handle_generate_bustup(mod: Any, args: dict[str, Any]) -> Any:
    """Handle ``generate_bustup`` schema."""
    person_dir = Path(args.pop("person_dir", ""))
    assets_dir = person_dir / "assets"
    ref_path = assets_dir / "avatar_fullbody.png"
    if not ref_path.exists():
        return {"error": "No full-body reference image found"}
    client = mod.FluxKontextClient()
    img = client.generate_from_reference(
        reference_image=ref_path.read_bytes(),
        prompt=args.get("prompt", mod._BUSTUP_PROMPT),
        aspect_ratio="3:4",
    )
    out = assets_dir / "avatar_bustup.png"
    out.write_bytes(img)
    return {"path": str(out), "size": len(img)}


def _handle_generate_chibi(mod: Any, args: dict[str, Any]) -> Any:
    """Handle ``generate_chibi`` schema."""
    person_dir = Path(args.pop("person_dir", ""))
    assets_dir = person_dir / "assets"
    ref_path = assets_dir / "avatar_fullbody.png"
    if not ref_path.exists():
        return {"error": "No full-body reference image found"}
    client = mod.FluxKontextClient()
    img = client.generate_from_reference(
        reference_image=ref_path.read_bytes(),
        prompt=args.get("prompt", mod._CHIBI_PROMPT),
        aspect_ratio="1:1",
    )
    out = assets_dir / "avatar_chibi.png"
    out.write_bytes(img)
    return {"path": str(out), "size": len(img)}


def _handle_generate_3d_model(mod: Any, args: dict[str, Any]) -> Any:
    """Handle ``generate_3d_model`` schema."""
    person_dir = Path(args.pop("person_dir", ""))
    assets_dir = person_dir / "assets"
    chibi_path = assets_dir / "avatar_chibi.png"
    if not chibi_path.exists():
        return {"error": "No chibi image found for 3D conversion"}
    client = mod.MeshyClient()
    task_id = client.create_task(
        chibi_path.read_bytes(),
        ai_model=args.get("ai_model", "meshy-6"),
        target_polycount=args.get("target_polycount", 30000),
    )
    task = client.poll_task(task_id)
    glb = client.download_model(task, fmt="glb")
    out = assets_dir / "avatar_chibi.glb"
    out.write_bytes(glb)
    return {"path": str(out), "size": len(glb), "task_id": task_id}


def _handle_generate_rigged_model(mod: Any, args: dict[str, Any]) -> Any:
    """Handle ``generate_rigged_model`` schema."""
    import httpx as _httpx

    person_dir = Path(args.pop("person_dir", ""))
    assets_dir = person_dir / "assets"
    glb_path = assets_dir / "avatar_chibi.glb"
    if not glb_path.exists():
        return {"error": "No 3D model found for rigging"}
    client = mod.MeshyClient()
    data_uri = mod._image_to_data_uri(
        glb_path.read_bytes(), mime="model/gltf-binary",
    )
    body = {
        "model_url": data_uri,
        "height_meters": args.get("height_meters", 1.0),
    }
    resp = _httpx.post(
        mod.MESHY_RIGGING_URL,
        json=body,
        headers=client._headers(),
        timeout=mod._HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    rig_task_id = resp.json()["result"]
    rig_task = client.poll_rigging_task(rig_task_id)
    rigged = client.download_rigged_model(rig_task, fmt="glb")
    rigged_path = assets_dir / "avatar_chibi_rigged.glb"
    rigged_path.write_bytes(rigged)
    basic_anims = client.download_rigging_animations(rig_task)
    anim_results: dict[str, str] = {}
    for anim_name, anim_bytes in basic_anims.items():
        anim_path = assets_dir / f"anim_{anim_name}.glb"
        anim_path.write_bytes(anim_bytes)
        anim_results[anim_name] = str(anim_path)
    return {
        "rigged_model": str(rigged_path),
        "animations": anim_results,
        "rig_task_id": rig_task_id,
    }


def _handle_generate_animations(mod: Any, args: dict[str, Any]) -> Any:
    """Handle ``generate_animations`` schema."""
    import httpx as _httpx

    person_dir = Path(args.pop("person_dir", ""))
    assets_dir = person_dir / "assets"
    glb_path = assets_dir / "avatar_chibi.glb"
    if not glb_path.exists():
        return {"error": "No 3D model found for animation"}
    client = mod.MeshyClient()
    data_uri = mod._image_to_data_uri(
        glb_path.read_bytes(), mime="model/gltf-binary",
    )
    body = {"model_url": data_uri, "height_meters": 1.0}
    resp = _httpx.post(
        mod.MESHY_RIGGING_URL,
        json=body,
        headers=client._headers(),
        timeout=mod._HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    rig_task_id = resp.json()["result"]
    client.poll_rigging_task(rig_task_id)
    anim_map = args.get("animations") or mod._DEFAULT_ANIMATIONS
    anim_results_gen: dict[str, str] = {}
    for anim_name, action_id in anim_map.items():
        anim_task_id = client.create_animation_task(rig_task_id, action_id)
        anim_task = client.poll_animation_task(anim_task_id)
        anim_bytes = client.download_animation(anim_task, fmt="glb")
        anim_path = assets_dir / f"anim_{anim_name}.glb"
        anim_path.write_bytes(anim_bytes)
        anim_results_gen[anim_name] = str(anim_path)
    return {"animations": anim_results_gen, "rig_task_id": rig_task_id}


# ── Dispatch table ───────────────────────────────────────────

_DISPATCH_TABLE: dict[str, Callable[[Any, dict[str, Any]], Any]] = {
    "web_search": _handle_web_search,
    "x_search": _handle_x_search,
    "x_user_tweets": _handle_x_user_tweets,
    "chatwork_send": _handle_chatwork_send,
    "chatwork_messages": _handle_chatwork_messages,
    "chatwork_search": _handle_chatwork_search,
    "chatwork_unreplied": _handle_chatwork_unreplied,
    "chatwork_rooms": _handle_chatwork_rooms,
    "slack_send": _handle_slack_send,
    "slack_messages": _handle_slack_messages,
    "slack_search": _handle_slack_search,
    "slack_unreplied": _handle_slack_unreplied,
    "slack_channels": _handle_slack_channels,
    "gmail_unread": _handle_gmail_unread,
    "gmail_read_body": _handle_gmail_read_body,
    "gmail_draft": _handle_gmail_draft,
    "local_llm_generate": _handle_local_llm_generate,
    "local_llm_chat": _handle_local_llm_chat,
    "local_llm_models": _handle_local_llm_models,
    "local_llm_status": _handle_local_llm_status,
    "transcribe_audio": _handle_transcribe_audio,
    "aws_ecs_status": _handle_aws_ecs_status,
    "aws_error_logs": _handle_aws_error_logs,
    "aws_metrics": _handle_aws_metrics,
    "github_list_issues": _handle_github_list_issues,
    "github_create_issue": _handle_github_create_issue,
    "github_list_prs": _handle_github_list_prs,
    "github_create_pr": _handle_github_create_pr,
    "generate_character_assets": _handle_generate_character_assets,
    "generate_fullbody": _handle_generate_fullbody,
    "generate_bustup": _handle_generate_bustup,
    "generate_chibi": _handle_generate_chibi,
    "generate_3d_model": _handle_generate_3d_model,
    "generate_rigged_model": _handle_generate_rigged_model,
    "generate_animations": _handle_generate_animations,
}


def _execute(mod: Any, *, schema_name: str, args: dict[str, Any]) -> Any:
    """Execute the appropriate function for *schema_name*."""
    handler = _DISPATCH_TABLE.get(schema_name)
    if handler is None:
        raise ValueError(f"No handler for tool schema: {schema_name}")
    return handler(mod, args)


# ── ExternalToolDispatcher ───────────────────────────────────


class ExternalToolDispatcher:
    """Dispatch tool calls to external tool modules."""

    def __init__(
        self,
        tool_registry: list[str],
        personal_tools: dict[str, str] | None = None,
    ) -> None:
        self._registry = tool_registry
        self._personal_tools = personal_tools or {}

    def dispatch(self, name: str, args: dict[str, Any]) -> str | None:
        """Execute an external tool by schema name."""
        result = self._dispatch_core(name, args)
        if result is not None:
            return result
        result = self._dispatch_personal(name, args)
        if result is not None:
            return result
        return None

    def _dispatch_core(self, name: str, args: dict[str, Any]) -> str | None:
        """Dispatch to core tool modules."""
        if not self._registry:
            return None

        import importlib

        from core.tools import TOOL_MODULES

        for tool_name, module_path in TOOL_MODULES.items():
            if tool_name not in self._registry:
                continue
            try:
                mod = importlib.import_module(module_path)
                schemas = mod.get_tool_schemas() if hasattr(mod, "get_tool_schemas") else []
                schema_names = [s["name"] for s in schemas]
                if name not in schema_names:
                    continue

                result = _execute(mod, schema_name=name, args=args)
                if isinstance(result, (dict, list)):
                    return json.dumps(result, ensure_ascii=False, indent=2, default=str)
                return str(result) if result is not None else "(no output)"
            except Exception as e:
                logger.warning("External tool %s failed: %s", name, e)
                return f"Error executing {name}: {e}"

        return None

    def _dispatch_personal(self, name: str, args: dict[str, Any]) -> str | None:
        """Dispatch to personal tool modules."""
        if not self._personal_tools:
            return None

        import importlib.util

        for tool_name, file_path in self._personal_tools.items():
            try:
                spec = importlib.util.spec_from_file_location(
                    f"animaworks_personal_tool_{tool_name}", file_path,
                )
                if spec is None or spec.loader is None:
                    continue
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)  # type: ignore[union-attr]

                schemas = mod.get_tool_schemas() if hasattr(mod, "get_tool_schemas") else []
                schema_names = [s["name"] for s in schemas]
                if name not in schema_names:
                    continue

                if hasattr(mod, "dispatch"):
                    result = mod.dispatch(name, args)
                elif hasattr(mod, name):
                    result = getattr(mod, name)(**args)
                else:
                    logger.warning(
                        "Personal tool %s has schema '%s' but no dispatch or matching function",
                        tool_name, name,
                    )
                    return f"Error: personal tool '{tool_name}' has no handler for '{name}'"

                if isinstance(result, (dict, list)):
                    return json.dumps(result, ensure_ascii=False, indent=2, default=str)
                return str(result) if result is not None else "(no output)"
            except Exception as e:
                logger.warning("Personal tool %s (%s) failed: %s", tool_name, name, e)
                return f"Error executing personal tool {name}: {e}"

        return None
