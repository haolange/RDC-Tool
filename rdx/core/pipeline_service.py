"""Pipeline state inspection and shader artifact export service."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Any, Dict, List, Optional, Protocol, Tuple, runtime_checkable

from rdx.core.native_values import native_value

from rdx.models import (
    ArtifactRef,
    BlendState,
    DepthStencilState,
    GraphicsAPI,
    PipelineSnapshot,
    RenderTargetInfo,
    ResourceBindingEntry,
    ShaderExportBundle,
    ShaderInfo,
    ShaderStage,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

_rd_module: Any = None


def _get_rd() -> Any:
    """Internal helper."""
    global _rd_module
    if _rd_module is None:
        try:
            import renderdoc as _rd  # type: ignore[import-not-found]
        except ImportError:
            raise ImportError(
                "The 'renderdoc' Python module is not available.  "
                "Make sure you are running inside a RenderDoc replay "
                "context or that the renderdoc shared library directory "
                "is on sys.path / PYTHONPATH."
            ) from None
        _rd_module = _rd
    return _rd_module


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


@runtime_checkable
class SessionManager(Protocol):
    """Internal helper."""

    def get_controller(self, session_id: str) -> Any:
        """Internal helper."""
        ...

    def get_output(self, session_id: str) -> Any:
        """Internal helper."""
        ...


@runtime_checkable
class ArtifactStore(Protocol):
    """Internal helper."""

    async def store(
        self,
        data: bytes,
        *,
        mime: str,
        suffix: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> ArtifactRef:
        """Internal helper."""
        ...


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

_GRAPHICS_STAGES: Tuple[str, ...] = (
    "Vertex",
    "Hull",
    "Domain",
    "Geometry",
    "Pixel",
)

_COMPUTE_STAGES: Tuple[str, ...] = ("Compute",)


def _rd_shader_stages() -> List[Any]:
    """Internal helper."""
    rd = _get_rd()
    return [
        rd.ShaderStage.Vertex,
        rd.ShaderStage.Hull,
        rd.ShaderStage.Domain,
        rd.ShaderStage.Geometry,
        rd.ShaderStage.Pixel,
        rd.ShaderStage.Compute,
    ]


def _map_shader_stage(rd_stage: Any) -> ShaderStage:
    """Internal helper."""
    rd = _get_rd()
    mapping: Dict[Any, ShaderStage] = {
        rd.ShaderStage.Vertex: ShaderStage.VS,
        rd.ShaderStage.Hull: ShaderStage.HS,
        rd.ShaderStage.Domain: ShaderStage.DS,
        rd.ShaderStage.Geometry: ShaderStage.GS,
        rd.ShaderStage.Pixel: ShaderStage.PS,
        rd.ShaderStage.Compute: ShaderStage.CS,
    }
    return mapping.get(rd_stage, ShaderStage.PS)


def _our_stage_to_rd(stage: ShaderStage) -> Any:
    """Internal helper."""
    rd = _get_rd()
    mapping: Dict[ShaderStage, Any] = {
        ShaderStage.VS: rd.ShaderStage.Vertex,
        ShaderStage.HS: rd.ShaderStage.Hull,
        ShaderStage.DS: rd.ShaderStage.Domain,
        ShaderStage.GS: rd.ShaderStage.Geometry,
        ShaderStage.PS: rd.ShaderStage.Pixel,
        ShaderStage.CS: rd.ShaderStage.Compute,
    }
    result = mapping.get(stage)
    if result is None:
        raise ValueError(f"Unsupported shader stage for RenderDoc: {stage}")
    return result


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


def _map_graphics_api(rd_api: Any) -> GraphicsAPI:
    """Internal helper."""
    rd = _get_rd()
    mapping: Dict[Any, GraphicsAPI] = {
        rd.GraphicsAPI.D3D11: GraphicsAPI.D3D11,
        rd.GraphicsAPI.D3D12: GraphicsAPI.D3D12,
        rd.GraphicsAPI.Vulkan: GraphicsAPI.VULKAN,
        rd.GraphicsAPI.OpenGL: GraphicsAPI.OPENGL,
    }
    return mapping.get(rd_api, GraphicsAPI.UNKNOWN)


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


def _is_null_id(resource_id: Any) -> bool:
    """Internal helper."""
    rd = _get_rd()
    try:
        return resource_id == rd.ResourceId()
    except Exception:
        return resource_id is None


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


def _get_api_specific_state(controller: Any, rd_api: Any) -> Any:
    """Internal helper."""
    rd = _get_rd()
    if rd_api == rd.GraphicsAPI.D3D11:
        return controller.GetD3D11PipelineState()
    if rd_api == rd.GraphicsAPI.D3D12:
        return controller.GetD3D12PipelineState()
    if rd_api == rd.GraphicsAPI.Vulkan:
        return controller.GetVulkanPipelineState()
    if rd_api == rd.GraphicsAPI.OpenGL:
        return controller.GetOpenGLPipelineState()
    return None


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


def _extract_blend_state(api_state: Any, api: GraphicsAPI) -> List[BlendState]:
    """Internal helper."""
    blends: List[BlendState] = []
    if api_state is None:
        return blends

    try:
        if api in (GraphicsAPI.D3D11, GraphicsAPI.D3D12):
            raw_blends = api_state.outputMerger.blendState.blends
        elif api == GraphicsAPI.VULKAN:
            raw_blends = api_state.colorBlend.blends
        elif api == GraphicsAPI.OPENGL:
            raw_blends = api_state.framebuffer.blendState.blends
        else:
            return blends

        for b in raw_blends:
            blends.append(BlendState(
                enabled=bool(b.enabled),
                src_color=str(b.colorBlend.source),
                dst_color=str(b.colorBlend.destination),
                color_op=str(b.colorBlend.operation),
                src_alpha=str(b.alphaBlend.source),
                dst_alpha=str(b.alphaBlend.destination),
                alpha_op=str(b.alphaBlend.operation),
                write_mask=int(b.writeMask) if hasattr(b, "writeMask") else None,
                logic_op=str(b.logicOperation) if hasattr(b, "logicOperation") else None,
                logic_op_enabled=bool(b.logicOperationEnabled) if hasattr(b, "logicOperationEnabled") else None,
            ))
    except (AttributeError, TypeError) as exc:
        raise RuntimeError("Pipeline blend read failed") from exc

    return blends


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


def _extract_depth_stencil(api_state: Any, api: GraphicsAPI) -> DepthStencilState:
    if api in (GraphicsAPI.D3D11, GraphicsAPI.D3D12):
        raw = api_state.outputMerger.depthStencilState
        depth_enable, depth_write, stencil_enable = raw.depthEnable, raw.depthWrites, raw.stencilEnable
        depth_function = raw.depthFunction
    elif api == GraphicsAPI.VULKAN:
        raw = api_state.depthStencil
        depth_enable, depth_write, stencil_enable = raw.depthTestEnable, raw.depthWriteEnable, raw.stencilTestEnable
        depth_function = raw.depthFunction
    elif api == GraphicsAPI.OPENGL:
        raw = api_state.stencilState
        depth_enable, depth_write = api_state.depthState.depthEnable, api_state.depthState.depthWrites
        depth_function, stencil_enable = api_state.depthState.depthFunction, raw.stencilEnable
    else:
        raise ValueError("Unsupported graphics API depth/stencil state")
    return DepthStencilState(depth_test_enabled=bool(depth_enable), depth_write_enabled=bool(depth_write),
        depth_func=str(depth_function), stencil_enabled=bool(stencil_enable),
        front=native_value(raw.frontFace), back=native_value(raw.backFace), details=native_value(raw))


async def _extract_render_targets(
    pipe_state: Any,
    api: GraphicsAPI,
    controller: Any,
) -> Tuple[List[RenderTargetInfo], Optional[RenderTargetInfo]]:
    """Internal helper."""
    colour_targets: List[RenderTargetInfo] = []
    depth_target: Optional[RenderTargetInfo] = None

    textures = await asyncio.to_thread(controller.GetTextures)
    tex_by_id: Dict[Any, Any] = {tex.resourceId: tex for tex in textures}

    # ---- colour outputs ----
    try:
        output_descriptors = pipe_state.GetOutputTargets()
        for slot, desc in enumerate(output_descriptors):
            rid = desc.resource
            tex = tex_by_id.get(rid)
            rt = RenderTargetInfo(resource_id=str(rid), slot=slot, descriptor=native_value(desc))
            if tex is not None:
                rt.format = str(tex.format.Name()) if hasattr(tex.format, "Name") else str(tex.format)
                rt.width = int(tex.width)
                rt.height = int(tex.height)
                rt.is_srgb = "srgb" in rt.format.lower()
            colour_targets.append(rt)
    except (AttributeError, TypeError) as exc:
        raise RuntimeError("Pipeline color target read failed") from exc

    # ---- depth target ----
    try:
        depth_desc = pipe_state.GetDepthTarget()
        rid = depth_desc.resource
        if not _is_null_id(rid):
            tex = tex_by_id.get(rid)
            dt = RenderTargetInfo(resource_id=str(rid), descriptor=native_value(depth_desc))
            if tex is not None:
                dt.format = str(tex.format.Name()) if hasattr(tex.format, "Name") else str(tex.format)
                dt.width = int(tex.width)
                dt.height = int(tex.height)
            depth_target = dt
    except (AttributeError, TypeError) as exc:
        raise RuntimeError("Pipeline depth target read failed") from exc

    return colour_targets, depth_target


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


def _extract_viewport(api_state: Any, api: GraphicsAPI) -> List[Dict[str, Any]]:
    if api == GraphicsAPI.VULKAN:
        raw = [entry.vp for entry in api_state.viewportScissor.viewportScissors]
    else:
        raw = api_state.rasterizer.viewports
    return [dict(native_value(value), index=index) for index, value in enumerate(raw)]


def _extract_scissor(api_state: Any, api: GraphicsAPI) -> List[Dict[str, Any]]:
    if api == GraphicsAPI.VULKAN:
        raw = [entry.scissor for entry in api_state.viewportScissor.viewportScissors]
    else:
        raw = api_state.rasterizer.scissors
    return [dict(native_value(value), index=index) for index, value in enumerate(raw)]


PIPELINE_SECTIONS = {
    "shaders": ["shaders"], "output_targets": ["render_targets", "depth_target"],
    "topology": ["topology"], "viewports_scissors": ["viewports", "scissors"],
    "blend": ["blend_states", "blend_options"], "depth_stencil": ["depth_stencil"],
    "bindings": ["bindings"], "vertex_input": ["vertex_inputs"],
    "rasterizer": ["rasterizer"], "multisample": ["multisample"],
    "push_constants": ["push_constants"], "dynamic_state": ["dynamic_state"],
    "root_signature": ["root_signature"], "descriptor_heaps": ["descriptor_heaps"],
    "resource_states": ["resource_states"],
}


def _state_section(state: Any, api: GraphicsAPI, section: str) -> Dict[str, Any]:
    """Project an API's recorded state without inventing unavailable declarations."""
    paths = {
        "rasterizer": {"D3D11": "rasterizer.state", "D3D12": "rasterizer.state",
                       "Vulkan": "rasterizer", "OpenGL": "rasterizer.state"},
        "multisample": {"D3D11": "outputMerger", "D3D12": "outputMerger",
                        "Vulkan": "multisample", "OpenGL": "rasterizer.state"},
        "push_constants": {"Vulkan": "pushconsts"},
        "root_signature": {"D3D12": "rootSignature"},
        "descriptor_heaps": {"D3D12": "descriptorHeaps"},
        "resource_states": {"D3D12": "resourceStates", "Vulkan": "images"},
    }
    key = {GraphicsAPI.D3D11: "D3D11", GraphicsAPI.D3D12: "D3D12",
           GraphicsAPI.VULKAN: "Vulkan", GraphicsAPI.OPENGL: "OpenGL"}.get(api, "unknown")
    if section == "push_constants" and api == GraphicsAPI.VULKAN:
        data = bytes(state.pushconsts)
        ranges = []
        for stage in ("vertexShader", "tessControlShader", "tessEvalShader", "geometryShader",
                      "fragmentShader", "computeShader"):
            shader = getattr(state, stage)
            offset, size = int(shader.pushConstantRangeByteOffset), int(shader.pushConstantRangeByteSize)
            if size:
                if offset < 0 or offset + size > len(data):
                    raise ValueError("Recorded push constant range exceeds available bytes")
                ranges.append({"stage": stage, "byte_offset": offset, "byte_size": size,
                               "shader_id": str(shader.resourceId)})
        layouts = {name: {field: native_value(getattr(getattr(state, name), field)) for field in
                   ("pipelineComputeLayoutResourceId", "pipelinePreRastLayoutResourceId", "pipelineFragmentLayoutResourceId")}
                   for name in ("graphics", "compute")}
        return {"api": key, "status": "available", "data": native_value(data),
                "stage_ranges": ranges, "layouts": layouts}
    if section == "dynamic_state":
        if api != GraphicsAPI.VULKAN:
            return {"api": key, "status": "not_applicable"}
        return {"api": key, "status": "available", "declarations_status": "not_recorded",
                "effective_state": {name: native_value(getattr(state, name)) for name in
                    ("viewportScissor", "rasterizer", "multisample", "colorBlend", "depthStencil")}}
    path = paths[section].get(key)
    if path is None:
        return {"api": key, "status": "not_applicable"}
    value = state
    for part in path.split("."):
        value = getattr(value, part)
    return {"api": key, "status": "available", "data": native_value(value)}


def _extract_topology(api_state: Any, api: GraphicsAPI) -> str:
    """Internal helper."""
    try:
        if api in (GraphicsAPI.D3D11, GraphicsAPI.D3D12, GraphicsAPI.VULKAN):
            return str(api_state.inputAssembly.topology)
        if api == GraphicsAPI.OPENGL:
            return str(api_state.vertexInput.topology)
    except (AttributeError, TypeError) as exc:
        logger.debug("_extract_topology: %s", exc)
    return ""


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


def _collect_bindings_for_stage(
    pipe: Any,
    rd_stage: Any,
    our_stage: ShaderStage,
) -> List[ResourceBindingEntry]:
    """Extract resource bindings for one shader stage across API variants."""
    rd = _get_rd()
    entries: List[ResourceBindingEntry] = []
    reflection = pipe.GetShaderReflection(rd_stage)
    seen: set[tuple[Any, ...]] = set()

    def _descriptor_kind(raw_type: Any, default_kind: str) -> str:
        try:
            dt = int(raw_type)
        except Exception:
            dt = None
        if dt is None:
            return default_kind
        try:
            if dt == int(rd.DescriptorType.ConstantBuffer):
                return "CBV"
            if dt == int(rd.DescriptorType.Sampler):
                return "Sampler"
            if dt in {
                int(rd.DescriptorType.ReadWriteImage),
                int(rd.DescriptorType.ReadWriteTypedBuffer),
                int(rd.DescriptorType.ReadWriteBuffer),
            }:
                return "UAV"
            if dt in {
                int(rd.DescriptorType.ImageSampler),
                int(rd.DescriptorType.Image),
                int(rd.DescriptorType.Buffer),
                int(rd.DescriptorType.TypedBuffer),
                int(rd.DescriptorType.AccelerationStructure),
            }:
                return "SRV"
        except Exception:
            pass
        return default_kind

    def _append_entry(
        *,
        set_or_space: int,
        binding: int,
        resource_id: str,
        binding_type: str,
        fmt: str = "",
        resource_name: str = "",
        array_index: int = 0,
        binding_source: str = "shader_reflection",
        descriptor: Optional[Dict[str, Any]] = None,
        sampler: Optional[Dict[str, Any]] = None,
        access: Optional[Dict[str, Any]] = None,
    ) -> None:
        location = access or {}
        key = (set_or_space, binding, binding_type, resource_id, array_index,
               location.get("descriptorStore"), location.get("byteOffset"))
        if key in seen:
            return
        seen.add(key)
        entries.append(
            ResourceBindingEntry(
                set_or_space=set_or_space,
                binding=binding,
                resource_id=resource_id,
                resource_name=resource_name,
                stage=our_stage.value,
                array_index=array_index,
                binding_source=binding_source,
                type=binding_type,
                format=fmt,
                descriptor=descriptor or {}, sampler=sampler or {}, access=access or {},
            ),
        )

    def _iter_new_descriptors(raw_items: Any, default_kind: str) -> None:
        items = list(raw_items or [])
        for item in items:
            access = item.access
            descriptor = item.descriptor
            index = int(access.index)
            reflection_list = getattr(reflection, {"SRV": "readOnlyResources", "UAV": "readWriteResources", "CBV": "constantBlocks", "Sampler": "samplers"}[default_kind], []) if reflection is not None else []
            reflected = reflection_list[index] if 0 <= index < len(reflection_list) else None
            binding = int(reflected.fixedBindNumber) if reflected is not None else -1
            set_or_space = int(reflected.fixedBindSetOrSpace) if reflected is not None else -1
            rid_raw = getattr(descriptor, "resource", None)
            resource_id = ""
            if rid_raw is not None and not _is_null_id(rid_raw):
                resource_id = str(rid_raw)
            kind = "Sampler" if default_kind == "Sampler" else _descriptor_kind(getattr(descriptor, "type", None), default_kind)
            fmt = str(descriptor.format.Name()) if hasattr(descriptor, "format") else ""
            _append_entry(
                set_or_space=set_or_space,
                binding=binding,
                resource_id=resource_id,
                binding_type=kind,
                fmt=fmt,
                resource_name=str(reflected.name) if reflected is not None else "",
                array_index=int(access.arrayElement),
                binding_source="shader_reflection" if reflected is not None else "direct_descriptor_access",
                descriptor=native_value(descriptor), access=native_value(access),
                sampler=native_value(item.sampler) if default_kind == "Sampler" else {},
            )

    _iter_new_descriptors(pipe.GetReadOnlyResources(rd_stage), "SRV")
    _iter_new_descriptors(pipe.GetReadWriteResources(rd_stage), "UAV")
    _iter_new_descriptors(pipe.GetConstantBlocks(rd_stage), "CBV")
    _iter_new_descriptors(pipe.GetSamplers(rd_stage), "Sampler")

    return entries
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


def _reflection_to_dict(refl: Any) -> Dict[str, Any]:
    """Internal helper."""
    result: Dict[str, Any] = {}

    # ---- Input / output signatures ----
    for sig_name in ("inputSignature", "outputSignature"):
        try:
            sig_list = getattr(refl, sig_name, None)
            if sig_list is not None:
                result[sig_name] = [
                    {
                        "varName": str(s.varName),
                        "semanticName": str(s.semanticName),
                        "semanticIndex": int(s.semanticIndex),
                        "regIndex": int(s.regIndex),
                        "compCount": int(s.compCount),
                        "compType": str(s.compType),
                    }
                    for s in sig_list
                ]
        except (AttributeError, TypeError):
            pass

    # ---- Constant blocks ----
    try:
        cb_list = refl.constantBlocks
        result["constantBlocks"] = [
            {
                "name": str(cb.name),
                "bindPoint": int(cb.bindPoint),
                "byteSize": int(cb.byteSize),
                "variables": [
                    {
                        "name": str(v.name),
                        "type": str(v.type.descriptor.name) if hasattr(v.type, "descriptor") else str(v.type),
                        "byteOffset": int(v.byteOffset),
                    }
                    for v in (cb.variables or [])
                ],
            }
            for cb in cb_list
        ]
    except (AttributeError, TypeError):
        pass

    # ---- Read-only resources ----
    try:
        ro_list = refl.readOnlyResources
        result["readOnlyResources"] = [
            {
                "name": str(r.name),
                "bindPoint": int(r.bindPoint),
                "isTexture": bool(r.isTexture),
                "resType": str(r.resType),
            }
            for r in ro_list
        ]
    except (AttributeError, TypeError):
        pass

    # ---- Read-write resources ----
    try:
        rw_list = refl.readWriteResources
        result["readWriteResources"] = [
            {
                "name": str(r.name),
                "bindPoint": int(r.bindPoint),
                "isTexture": bool(r.isTexture),
                "resType": str(r.resType),
            }
            for r in rw_list
        ]
    except (AttributeError, TypeError):
        pass

    return result


# ---------------------------------------------------------------------------
# PipelineService
# ---------------------------------------------------------------------------


class PipelineService:
    """Internal helper."""

    # ------------------------------------------------------------------
    # snapshot_pipeline
    # ------------------------------------------------------------------

    async def snapshot_pipeline(
        self,
        session_id: str,
        event_id: int,
        session_manager: SessionManager,
        *,
        sections: Optional[List[str]] = None,
    ) -> PipelineSnapshot:
        """Internal helper."""
        selected = set(sections) if sections is not None else set(PIPELINE_SECTIONS)
        rd = _get_rd()
        controller = session_manager.get_controller(session_id)

        await asyncio.to_thread(controller.SetFrameEvent, event_id, True)

        pipe = await asyncio.to_thread(controller.GetPipelineState)
        api_props = await asyncio.to_thread(controller.GetAPIProperties)
        api = _map_graphics_api(api_props.pipelineType)

        # API-specific state for blend / depth / viewport / topology.
        api_state = None
        if selected - {"shaders", "output_targets", "bindings", "vertex_input"}:
            api_state = await asyncio.to_thread(_get_api_specific_state, controller, api_props.pipelineType)

        shader_resources = {str(r.resourceId): r for r in controller.GetResources()} if "shaders" in selected else {}
        shaders: List[ShaderInfo] = []
        for rd_stage in (_rd_shader_stages() if "shaders" in selected else []):
            try:
                shader_id = pipe.GetShader(rd_stage)
                if _is_null_id(shader_id):
                    continue

                refl = pipe.GetShaderReflection(rd_stage)
                entry_point = "main"
                encoding = ""
                if refl is not None:
                    if hasattr(refl, "entryPoint"):
                        entry_point = str(refl.entryPoint)
                    if hasattr(refl, "encoding"):
                        encoding = str(refl.encoding)

                from rdx.core.replay_facts import shader_content_hash
                shaders.append(ShaderInfo(
                    hash=shader_content_hash(refl),
                    debug_name=(str(shader_resources[str(shader_id)].name) if str(shader_id) in shader_resources and not shader_resources[str(shader_id)].autogeneratedName else None),
                    resource_name=(str(shader_resources[str(shader_id)].name) if str(shader_id) in shader_resources else None),
                    debug_source_files=[str(f.filename) for f in getattr(getattr(refl, "debugInfo", None), "files", [])],
                    resource_id=str(shader_id),
                    stage=_map_shader_stage(rd_stage),
                    entry_point=entry_point,
                    encoding=encoding,
                ))
            except Exception as exc:
                raise RuntimeError(f"Pipeline shader read failed at stage {rd_stage}") from exc

        render_targets, depth_target = [], None
        if "output_targets" in selected:
            render_targets, depth_target = await _extract_render_targets(pipe, api, controller)

        blend_states = _extract_blend_state(api_state, api) if "blend" in selected else []

        blend_options = {}
        if "blend" in selected:
            if api in (GraphicsAPI.D3D11, GraphicsAPI.D3D12):
                blend_options = native_value(api_state.outputMerger.blendState)
            elif api == GraphicsAPI.VULKAN:
                blend_options = native_value(api_state.colorBlend)
            elif api == GraphicsAPI.OPENGL:
                blend_options = native_value(api_state.framebuffer.blendState)
            blend_options.pop("blends", None)

        # ---- Depth / stencil state -----------------------------------
        depth_stencil = _extract_depth_stencil(api_state, api) if "depth_stencil" in selected else DepthStencilState()

        # ---- Viewport / scissor --------------------------------------
        viewport = _extract_viewport(api_state, api) if "viewports_scissors" in selected else []
        scissor = _extract_scissor(api_state, api) if "viewports_scissors" in selected else []

        # ---- Topology ------------------------------------------------
        topology = _extract_topology(api_state, api) if "topology" in selected else ""

        bindings: List[ResourceBindingEntry] = []
        for rd_stage in (_rd_shader_stages() if "bindings" in selected else []):
            try:
                shader_id = pipe.GetShader(rd_stage)
                if _is_null_id(shader_id):
                    continue
                stage_bindings = _collect_bindings_for_stage(
                    pipe, rd_stage, _map_shader_stage(rd_stage),
                )
                bindings.extend(stage_bindings)
            except Exception as exc:
                raise RuntimeError(f"Pipeline binding read failed at stage {rd_stage}") from exc

        return PipelineSnapshot(
            event_id=event_id,
            api=api,
            shaders=shaders,
            render_targets=render_targets,
            depth_target=depth_target,
            blend_states=blend_states,
            blend_options=blend_options,
            depth_stencil=depth_stencil,
            bindings=bindings,
            viewports=viewport,
            scissors=scissor,
            vertex_inputs=[native_value(v) for v in pipe.GetVertexInputs()] if "vertex_input" in selected else [],
            **{name: _state_section(api_state, api, name) for name in selected & {
                "rasterizer", "multisample", "push_constants", "dynamic_state",
                "root_signature", "descriptor_heaps", "resource_states"}},
            topology=topology,
        )

    # ------------------------------------------------------------------
    # export_shader
    # ------------------------------------------------------------------

    async def export_shader(
        self,
        session_id: str,
        event_id: int,
        stage: ShaderStage,
        session_manager: SessionManager,
        artifact_store: ArtifactStore,
    ) -> ShaderExportBundle:
        """Internal helper."""
        rd = _get_rd()
        controller = session_manager.get_controller(session_id)

        await asyncio.to_thread(controller.SetFrameEvent, event_id, True)

        pipe = await asyncio.to_thread(controller.GetPipelineState)
        rd_stage = _our_stage_to_rd(stage)

        shader_id = pipe.GetShader(rd_stage)
        if _is_null_id(shader_id):
            raise ValueError(
                f"No shader bound at stage {stage.value} for event {event_id}"
            )

        refl = pipe.GetShaderReflection(rd_stage)
        if refl is None:
            raise RuntimeError(
                f"Shader reflection unavailable for stage {stage.value} "
                f"at event {event_id}"
            )

        pipeline_rid = rd.ResourceId()
        try:
            if stage == ShaderStage.CS:
                pipeline_rid = pipe.GetComputePipelineObject()
            else:
                pipeline_rid = pipe.GetGraphicsPipelineObject()
        except (AttributeError, TypeError):
            pass

        entry_point = "main"
        encoding = ""
        if hasattr(refl, "entryPoint"):
            entry_point = str(refl.entryPoint)
        if hasattr(refl, "encoding"):
            encoding = str(refl.encoding)

        refl_dict = _reflection_to_dict(refl)
        refl_dict["_meta"] = {
            "event_id": event_id,
            "stage": stage.value,
            "shader_id": str(shader_id),
            "entry_point": entry_point,
            "encoding": encoding,
        }
        refl_bytes = json.dumps(refl_dict, indent=2, default=str).encode()
        refl_artifact = await artifact_store.store(
            refl_bytes,
            mime="application/json",
            suffix=".refl.json",
            meta={
                "event_id": event_id,
                "stage": stage.value,
                "kind": "shader_reflection",
            },
        )

        disasm_artifact: Optional[ArtifactRef] = None
        try:
            targets: List[str] = await asyncio.to_thread(
                controller.GetDisassemblyTargets, True,
            )

            if targets:
                sections: List[str] = []
                for target_name in targets:
                    try:
                        disasm_text: str = await asyncio.to_thread(
                            controller.DisassembleShader,
                            pipeline_rid,
                            refl,
                            target_name,
                        )
                        if disasm_text:
                            sections.append(
                                f";;; === {target_name} ===\n"
                                f"{disasm_text}"
                            )
                    except Exception as exc:
                        logger.debug(
                            "export_shader: disassembly target %r failed: %s",
                            target_name, exc,
                        )

                if sections:
                    combined = "\n\n".join(sections)
                    disasm_bytes = combined.encode("utf-8")
                    disasm_artifact = await artifact_store.store(
                        disasm_bytes,
                        mime="text/plain",
                        suffix=".disasm.txt",
                        meta={
                            "event_id": event_id,
                            "stage": stage.value,
                            "kind": "shader_disassembly",
                            "targets": [t for t in targets],
                        },
                    )
        except Exception as exc:
            logger.warning("export_shader: disassembly failed: %s", exc)

        # ---- Compute a content hash for the shader -------------------
        shader_hash = ""
        try:
            shader_hash = hashlib.sha256(refl_bytes).hexdigest()[:16]
        except Exception:
            pass

        return ShaderExportBundle(
            shader_id=str(shader_id),
            stage=stage,
            entry_point=entry_point,
            encoding=encoding,
            reflection_artifact=refl_artifact,
            disasm_artifact=disasm_artifact,
        )

    # ------------------------------------------------------------------
    # get_resource_bindings
    # ------------------------------------------------------------------

    async def get_resource_bindings(
        self,
        session_id: str,
        event_id: int,
        session_manager: SessionManager,
        *, stage: Optional[ShaderStage] = None,
    ) -> List[ResourceBindingEntry]:
        """Internal helper."""
        rd = _get_rd()
        controller = session_manager.get_controller(session_id)

        await asyncio.to_thread(controller.SetFrameEvent, event_id, True)

        pipe = await asyncio.to_thread(controller.GetPipelineState)

        entries: List[ResourceBindingEntry] = []
        for rd_stage in ([_our_stage_to_rd(stage)] if stage is not None else _rd_shader_stages()):
            try:
                shader_id = pipe.GetShader(rd_stage)
                if _is_null_id(shader_id):
                    continue

                our_stage = _map_shader_stage(rd_stage)
                stage_entries = _collect_bindings_for_stage(
                    pipe, rd_stage, our_stage,
                )

                entries.extend(stage_entries)
            except Exception as exc:
                raise RuntimeError(f"Pipeline binding read failed at stage {rd_stage}") from exc

        return entries


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
