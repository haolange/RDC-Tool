"""rd.resource.* operations."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence, Tuple

from rdc_tool.runtime import coerce, envelope, live_state, renderdoc_api, replay_access, texture_naming


async def dispatch(action: str, args: Dict[str, Any]) -> str:
    coerce._require(args, "session_id")
    session_id = str(args["session_id"])
    controller = await replay_access._get_controller(session_id)
    binding_index_cache: Optional[Dict[str, List[str]]] = None
    event_lookup_cache: Optional[Dict[int, Any]] = None

    async def get_binding_index() -> Dict[str, List[str]]:
        nonlocal binding_index_cache
        if binding_index_cache is None:
            binding_index_cache = await replay_access._binding_name_index_for_event(
                session_id,
                replay_access._active_event(session_id),
            )
        return binding_index_cache

    async def get_event_lookup() -> Dict[int, Any]:
        nonlocal event_lookup_cache
        if event_lookup_cache is None:
            _, _, event_lookup_cache = await replay_access._load_action_index(session_id, controller=controller)
        return event_lookup_cache

    async def usage_event_payload(entry: Any) -> Dict[str, Any]:
        raw_event_id = int(getattr(entry, "eventId", 0))
        event_lookup = await get_event_lookup()
        resolvable = raw_event_id > 0 and raw_event_id in event_lookup
        action = event_lookup.get(raw_event_id)
        color = [{"slot": slot, "resource_id": str(resource)} for slot, resource in enumerate(getattr(action, "outputs", None) or []) if not renderdoc_api._is_null_resource_id(resource)] if action else None
        depth = getattr(action, "depthOut", None)
        return {
            "attachments": {"color": color, "depth": None if renderdoc_api._is_null_resource_id(depth) else str(depth)},
            "event_id": raw_event_id if resolvable else None,
            "raw_event_id": raw_event_id,
            "event_resolvable": resolvable,
        }

    async def list_textures(textures: Optional[Sequence[Any]] = None) -> List[Dict[str, Any]]:
        if textures is None:
            textures = await renderdoc_api._offload(controller.GetTextures)
        binding_index = await get_binding_index()
        out = []
        for tex in textures:
            rid = getattr(tex, "resourceId", None)
            rid_text = str(rid)
            binding_names = list(binding_index.get(rid_text, []))
            alias_name = live_state._runtime.aliases.get(rid_text, "")
            name_info = texture_naming._compose_texture_name_info(
                rid_text,
                resource_name=str(getattr(tex, "name", "")),
                binding_names=binding_names,
                alias_name=alias_name,
            )
            out.append(
                {
                    "resource_id": rid_text,
                    "texture_id": rid_text,
                    "name": name_info["display_name"],
                    "resource_name": name_info["resource_name"],
                    "alias_name": name_info["alias_name"],
                    "binding_names": name_info["binding_names"],
                    "name_stem": name_info["name_stem"],
                    "width": int(getattr(tex, "width", 0)),
                    "height": int(getattr(tex, "height", 0)),
                    "depth": int(getattr(tex, "depth", 0)),
                    "mips": int(getattr(tex, "mips", 1)),
                    "format": str(getattr(getattr(tex, "format", None), "Name", lambda: str(getattr(tex, "format", "")))()),
                },
            )
        return out

    async def list_buffers(buffers: Optional[Sequence[Any]] = None) -> List[Dict[str, Any]]:
        if buffers is None:
            buffers = await renderdoc_api._offload(controller.GetBuffers)
        out = []
        for buf in buffers:
            rid = getattr(buf, "resourceId", None)
            rid_text = str(rid)
            out.append(
                {
                    "resource_id": rid_text,
                    "buffer_id": rid_text,
                    "name": live_state._runtime.aliases.get(rid_text, str(getattr(buf, "name", ""))),
                    "length": int(getattr(buf, "length", 0)),
                    "byte_size": int(getattr(buf, "length", 0)),
                },
            )
        return out

    async def load_identity_inventory() -> Tuple[Any, Any, Any, Any]:
        # The same native census qualifies both details resolution and public absence checks.
        return (await renderdoc_api._offload(controller.GetTextures), await renderdoc_api._offload(controller.GetBuffers),
                await renderdoc_api._offload(controller.GetDescriptorStores), await renderdoc_api._offload(controller.GetResources))

    async def list_descriptor_stores(stores: Optional[Sequence[Any]] = None) -> List[Dict[str, Any]]:
        from rdc_tool.core.native_values import native_value
        if stores is None:
            stores = await renderdoc_api._offload(controller.GetDescriptorStores)
        return [{"resource_id": str(store.resourceId), "kind": "descriptor_store",
                 **native_value(store)} for store in stores]

    if action == "get_descriptors":
        from rdc_tool.core.native_values import native_value
        coerce._require(args, "descriptor_store_id")
        await replay_access._ensure_event(session_id, args.get("event_id"))
        stores = await renderdoc_api._offload(controller.GetDescriptorStores)
        store = next((item for item in stores if str(item.resourceId) == str(args["descriptor_store_id"])), None)
        if store is None:
            return envelope._err("Descriptor store not found", code="resource_not_found")
        first, count = int(args.get("first", 0)), int(args.get("count", 64))
        kind = str(args.get("type", "resource"))
        if first < 0 or not 1 <= count <= 1024 or first > store.descriptorCount or kind not in {"resource", "sampler"}:
            return envelope._err("Invalid descriptor range or type", code="validation_error")
        count = min(count, store.descriptorCount-first)
        if count == 0:
            return envelope._ok(descriptors=[], total=store.descriptorCount, next_first=None)
        rd = renderdoc_api._get_rd()
        descriptor_range = rd.DescriptorRange()
        descriptor_range.offset = store.firstDescriptorOffset + first * store.descriptorByteSize
        descriptor_range.descriptorSize = store.descriptorByteSize
        descriptor_range.count = count
        descriptor_range.type = rd.DescriptorType.Sampler if kind == "sampler" else rd.DescriptorType.Unknown
        reader = controller.GetSamplerDescriptors if kind == "sampler" else controller.GetDescriptors
        values = await renderdoc_api._offload(reader, store.resourceId, [descriptor_range])
        locations = await renderdoc_api._offload(controller.GetDescriptorLocations, store.resourceId, [descriptor_range])
        if len(values) != count or len(locations) != count:
            return envelope._err("Incomplete descriptor range read", code="descriptor_read_failed")
        return envelope._ok(descriptor_store_id=str(store.resourceId), resolved_event_id=replay_access._active_event(session_id),
            descriptors=[{"index": first+i, "descriptor": native_value(value),
                          "location": native_value(locations[i])} for i, value in enumerate(values)],
            total=store.descriptorCount,
            next_first=first+count if first+count < store.descriptorCount else None)

    if action == "list_all":
        kind = args.get("kind", "all")
        if kind not in {"all", "texture", "buffer", "descriptor_store"}:
            return envelope._err("Invalid resource kind", code="validation_error")
        payload: Dict[str, Any] = {}
        if kind == "all":
            native_textures, native_buffers, native_stores, descriptions = await load_identity_inventory()
            textures = await list_textures(native_textures)
            buffers = await list_buffers(native_buffers)
            stores = await list_descriptor_stores(native_stores)
            ids: Dict[str, str] = {}
            for collection in (native_textures, native_buffers, native_stores, descriptions):
                for item in collection:
                    tokens = texture_naming._resource_id_tokens(item.resourceId)
                    if not tokens:
                        raise ValueError("Native resource inventory contains an empty identity")
                    ids.setdefault(tokens[-1], str(item.resourceId))
            payload["identity_inventory"] = {
                "scope": "all_native_resource_identities", "complete": True,
                "resource_ids": list(ids.values()), "count": len(ids),
                "source_counts": {"textures": len(native_textures), "buffers": len(native_buffers),
                                  "descriptor_stores": len(native_stores), "descriptions": len(descriptions)},
            }
        else:
            textures = await list_textures() if kind == "texture" else []
            buffers = await list_buffers() if kind == "buffer" else []
            stores = await list_descriptor_stores() if kind == "descriptor_store" else []
        resources = textures + buffers + stores
        payload["resources"] = resources
        projection = envelope._projection_request(args, "rd.resource.list_all")
        if projection:
            payload["projections"] = envelope._resource_rows_projection(
                resources, include_tsv_text=bool(projection.get("include_tsv_text", False)))
        return envelope._ok(**payload)
    if action == "get_details":
        coerce._require(args, "resource_id")
        requested = args["resource_id"]
        # Complete the read-only inventory before optional binding enrichment,
        # which can inspect/repair a replay position. Only this miss is pre-effect.
        textures, buffers, stores, descriptions = await load_identity_inventory()
        matched = next((item.resourceId
                        for collection in (textures, buffers, stores, descriptions)
                        for item in collection if texture_naming._resource_id_matches(item.resourceId, requested)), None)
        if matched is None:
            return envelope._err(f"Resource not found: {requested}", code="resource_not_found", category="validation",
                        details={"session_id": session_id, "failure_stage": "resolve_resource",
                                 "effects_attempted": False, "context_preserved": True})
        rid = str(matched)
        resources = (await list_textures(textures)) + (await list_buffers(buffers)) + (await list_descriptor_stores(stores))
        description = next((item for item in descriptions if texture_naming._resource_id_matches(item.resourceId, matched)), None)
        details = next((item for item in resources if item.get("resource_id") == rid), None)
        if details is None and description is not None:
            details = {"resource_id": rid, "name": str(description.name)}
        if details is None:
            return envelope._err(f"Resource metadata unavailable: {rid}", code="resource_details_unavailable")
        if args.get("include_initialization", False):
            details["initialization"] = ({"status": "available",
                "chunk_indices": [int(index) for index in description.initialisationChunks],
                "parent_resources": [str(value) for value in description.parentResources],
                "derived_resources": [str(value) for value in description.derivedResources],
                "scope": "captured_initialization"} if description is not None else
                {"status": "not_recorded"})
        return envelope._ok(details=details)
    if action == "get_usage":
        coerce._require(args, "resource_id")
        rid = await replay_access._resolve_resource_id(session_id, args["resource_id"])
        from rdc_tool.core.replay_facts import usage_access
        usage_raw = await renderdoc_api._offload(controller.GetUsage, rid)
        usage = []
        for entry in usage_raw:
            event_info = await usage_event_payload(entry)
            usage.append(
                {
                    **event_info,
                    "usage": str(getattr(entry, "usage", "")),
                    **usage_access(renderdoc_api._get_rd(), entry.usage),
                },
            )
        return envelope._ok(usage=usage[: coerce._as_int(args.get("max_events"), 10000)])
    if action == "set_alias":
        coerce._require(args, "resource_id", "alias")
        live_state._runtime.aliases[str(args["resource_id"])] = str(args["alias"])
        return envelope._ok()
    if action == "estimate_memory":
        if args.get("resource_id") is not None:
            details_response = await dispatch("get_details", {"session_id": session_id, "resource_id": args["resource_id"]})
            payload = json.loads(details_response)
            if not payload.get("success"):
                return details_response
            details = payload.get("details", {})
            bytes_est = int(details.get("byte_size") or (details.get("width", 0) * details.get("height", 0) * 4))
            return envelope._ok(memory={"bytes": bytes_est, "human": coerce._format_size(bytes_est)})
        textures = await list_textures()
        buffers = await list_buffers()
        total = sum(int(t.get("width", 0) * t.get("height", 0) * 4) for t in textures) + sum(int(b.get("byte_size", 0)) for b in buffers)
        return envelope._ok(memory={"bytes": total, "human": coerce._format_size(total)})
    return envelope._err(f"Unsupported resource action: {action}")
