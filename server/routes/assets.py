from __future__ import annotations
# AnimaWorks - Digital Person Framework
# Copyright (C) 2026 AnimaWorks Authors
# SPDX-License-Identifier: AGPL-3.0-or-later

import logging
import re
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

logger = logging.getLogger("animaworks.routes.assets")

_ASSET_CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".glb": "model/gltf-binary",
    ".gltf": "model/gltf+json",
}


class AssetGenerateRequest(BaseModel):
    prompt: str | None = None
    negative_prompt: str = ""
    steps: list[str] | None = None
    skip_existing: bool = True


def create_assets_router() -> APIRouter:
    router = APIRouter()

    @router.get("/persons/{name}/assets")
    async def list_assets(name: str, request: Request):
        """List available assets for a person."""
        person = request.app.state.persons.get(name)
        if not person:
            return JSONResponse({"error": "Person not found"}, status_code=404)
        assets_dir = person.person_dir / "assets"
        if not assets_dir.exists():
            return {"assets": []}
        return {
            "assets": [
                {"name": f.name, "size": f.stat().st_size}
                for f in sorted(assets_dir.iterdir())
                if f.is_file()
            ]
        }

    @router.get("/persons/{name}/assets/metadata")
    async def get_asset_metadata(name: str, request: Request):
        """Return structured metadata about a person's available assets."""
        person = request.app.state.persons.get(name)
        if not person:
            return JSONResponse({"error": "Person not found"}, status_code=404)

        assets_dir = person.person_dir / "assets"
        base_url = f"/api/persons/{name}/assets"

        asset_files = {
            "avatar_fullbody": "avatar_fullbody.png",
            "avatar_bustup": "avatar_bustup.png",
            "avatar_chibi": "avatar_chibi.png",
            "model_chibi": "avatar_chibi.glb",
            "model_rigged": "avatar_chibi_rigged.glb",
        }

        result: dict = {"name": name, "assets": {}, "animations": {}, "colors": None}

        if assets_dir.exists():
            for key, filename_ in asset_files.items():
                path = assets_dir / filename_
                if path.exists():
                    result["assets"][key] = {
                        "filename": filename_,
                        "url": f"{base_url}/{filename_}",
                        "size": path.stat().st_size,
                    }

            for f in sorted(assets_dir.iterdir()):
                if f.is_file() and f.name.startswith("anim_") and f.suffix == ".glb":
                    anim_name = f.stem[len("anim_"):]
                    result["animations"][anim_name] = {
                        "filename": f.name,
                        "url": f"{base_url}/{f.name}",
                        "size": f.stat().st_size,
                    }

        # Extract image_color from identity.md
        identity_path = person.person_dir / "identity.md"
        if identity_path.exists():
            try:
                text = identity_path.read_text(encoding="utf-8")
                match = re.search(
                    r"(?:イメージカラー|image[_ ]?color|カラー)\s*[:：]\s*.*?(#[0-9A-Fa-f]{6})",
                    text,
                )
                if match:
                    result["colors"] = {"image_color": match.group(1)}
            except OSError:
                pass

        return result

    @router.api_route("/persons/{name}/assets/{filename}", methods=["GET", "HEAD"])
    async def get_asset(name: str, filename: str, request: Request):
        """Serve a static asset file from a person's assets directory."""
        person = request.app.state.persons.get(name)
        if not person:
            return JSONResponse({"error": "Person not found"}, status_code=404)

        # Validate filename (prevent path traversal)
        safe_name = Path(filename).name
        if safe_name != filename or ".." in filename:
            return JSONResponse({"error": "Invalid filename"}, status_code=400)

        file_path = person.person_dir / "assets" / safe_name
        if not file_path.exists() or not file_path.is_file():
            return JSONResponse({"error": "Asset not found"}, status_code=404)

        suffix = file_path.suffix.lower()
        content_type = _ASSET_CONTENT_TYPES.get(suffix, "application/octet-stream")
        return FileResponse(
            file_path,
            media_type=content_type,
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @router.post("/persons/{name}/assets/generate")
    async def generate_assets(
        name: str, body: AssetGenerateRequest, request: Request,
    ):
        """Trigger character asset generation pipeline."""
        import asyncio

        person = request.app.state.persons.get(name)
        if not person:
            return JSONResponse({"error": "Person not found"}, status_code=404)

        prompt = body.prompt
        if not prompt:
            return JSONResponse(
                {"error": "prompt is required"}, status_code=400,
            )

        from core.tools.image_gen import ImageGenPipeline

        pipeline = ImageGenPipeline(person.person_dir)

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: pipeline.generate_all(
                prompt=prompt,
                negative_prompt=body.negative_prompt,
                skip_existing=body.skip_existing,
                steps=body.steps,
            ),
        )

        # Broadcast asset update via WebSocket
        generated: list[str] = []
        if result.fullbody_path:
            generated.append("avatar_fullbody.png")
        if result.bustup_path:
            generated.append("avatar_bustup.png")
        if result.chibi_path:
            generated.append("avatar_chibi.png")
        if result.model_path:
            generated.append("avatar_chibi.glb")
        if result.rigged_model_path:
            generated.append("avatar_chibi_rigged.glb")
        for anim_name, anim_path in result.animation_paths.items():
            generated.append(anim_path.name)

        if generated:
            ws_manager = request.app.state.ws_manager
            await ws_manager.broadcast({
                "type": "person.assets_updated",
                "data": {
                    "name": name,
                    "assets": generated,
                    "errors": result.errors,
                },
            })

        return result.to_dict()

    return router
