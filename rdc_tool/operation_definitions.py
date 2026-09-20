"""Canonical public operation definitions. Catalogs and manuals are generated from this module."""
from __future__ import annotations

OPERATIONS = [{'name': 'rd.buffer.get_data',
  'group': '3.7，缓冲区与网格数据访问 (Buffer & Mesh Data Access)',
  'description': '读取 buffer 的原始字节数据（默认保存到文件以避免 JSON 过大）。',
  'parameter_raw': 'session_id (string): session_id (str)<br>buffer_id (string): buffer_id '
                   '(str)<br>offset (integer): offset (int, 可选, 默认 0)<br>size (integer): size '
                   '(int, 可选): 读取字节数；缺省为 buffer 末尾<br>output_path (string): output_path (str, 可选): '
                   '若提供则写入该文件，否则写入临时 artifact 文件<br>as_base64 (boolean): as_base64 (bool, 可选, 默认 '
                   'false): 小数据可直接 base64 返回<br>state (string): Recorded frame-initial contents or '
                   'current/requested event; reads restore the original replay event.<br>event_id '
                   '(integer): Current-state event to read; mutually exclusive with '
                   'capture_initial.',
  'returns_raw': 'data: resource identity, byte_size, state, resolved_event_id, restored_event_id, '
                 'replay_state_restored=true, initial_provenance; base64 when requested (1 MiB '
                 'limit, no automatic artifact), otherwise explicit output/artifact. Initial '
                 'provenance unavailable, failed/incomplete read and restoration failure are '
                 'distinct errors. Restoration failure requires closing and reopening the session.',
  'param_names': ['session_id',
                  'buffer_id',
                  'offset',
                  'size',
                  'output_path',
                  'as_base64',
                  'state',
                  'event_id'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'buffer',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'buffer_id': {'description': 'buffer_id (str)', 'type': 'string'},
                                  'offset': {'description': 'offset (int, 可选, 默认 0)',
                                             'type': 'integer',
                                             'minimum': 0},
                                  'size': {'description': 'size (int, 可选): 读取字节数；缺省为 buffer 末尾',
                                           'type': 'integer',
                                           'minimum': 0},
                                  'output_path': {'description': 'output_path (str, 可选): '
                                                                 '若提供则写入该文件，否则写入临时 artifact 文件',
                                                  'type': 'string'},
                                  'as_base64': {'description': 'as_base64 (bool, 可选, 默认 false): '
                                                               '小数据可直接 base64 返回',
                                                'type': 'boolean'},
                                  'state': {'type': 'string',
                                            'enum': ['current', 'capture_initial'],
                                            'default': 'current',
                                            'description': 'Recorded frame-initial contents or '
                                                           'current/requested event; reads restore '
                                                           'the original replay event.'},
                                  'event_id': {'type': 'integer',
                                               'minimum': 1,
                                               'description': 'Current-state event to read; '
                                                              'mutually exclusive with '
                                                              'capture_initial.'}},
                   'required': ['session_id', 'buffer_id'],
                   'additionalProperties': False,
                   'not': {'required': ['state', 'event_id'],
                           'properties': {'state': {'enum': ['capture_initial']}}}},
  'scope': 'replay',
  'effects': ['replay_position_temporary', 'artifact_write'],
  'evidence_kind': None,
  'path_inputs': [{'name': 'output_path', 'access': 'write'}]},
 {'name': 'rd.buffer.get_structured_data',
  'group': '3.7，缓冲区与网格数据访问 (Buffer & Mesh Data Access)',
  'description': '按结构化布局解码 buffer 内容（适用于 StructuredBuffer/SSBO/顶点数据等）。',
  'parameter_raw': 'session_id (string): session_id (str)<br>buffer_id (string): buffer_id '
                   '(str)<br>layout (object): layout (dict): 结构体布局定义，例如 {stride, '
                   'fields:[{name,type,offset,count?}]}<br>offset (integer, optional): offset '
                   '(int, 可选, 默认 0)<br>count (integer, optional): count (int, 可选): '
                   '解码元素个数<br>max_elements (integer, optional): max_elements (int, 可选, 默认 '
                   '4096)<br>size (integer, optional): See input_schema for constraints.',
  'returns_raw': 'ok (bool)<br>data (dict): {elements}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'buffer_id', 'layout', 'offset', 'count', 'max_elements', 'size'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'buffer',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'buffer_id': {'description': 'buffer_id (str)', 'type': 'string'},
                                  'layout': {'type': 'object',
                                             'properties': {'stride': {'type': 'integer',
                                                                       'minimum': 1},
                                                            'fields': {'type': 'array',
                                                                       'items': {'type': 'object',
                                                                                 'properties': {'name': {'type': 'string'},
                                                                                                'type': {'type': 'string',
                                                                                                         'enum': ['u8',
                                                                                                                  'i8',
                                                                                                                  'u16',
                                                                                                                  'i16',
                                                                                                                  'u32',
                                                                                                                  'i32',
                                                                                                                  'f32']},
                                                                                                'offset': {'type': 'integer',
                                                                                                           'minimum': 0},
                                                                                                'count': {'type': 'integer',
                                                                                                          'minimum': 1}},
                                                                                 'required': ['name',
                                                                                              'type',
                                                                                              'offset'],
                                                                                 'additionalProperties': False}}},
                                             'required': ['stride', 'fields'],
                                             'additionalProperties': False},
                                  'offset': {'description': 'offset (int, 可选, 默认 0)',
                                             'type': 'integer',
                                             'minimum': 0},
                                  'count': {'description': 'count (int, 可选): 解码元素个数',
                                            'type': 'integer'},
                                  'max_elements': {'description': 'max_elements (int, 可选, 默认 4096)',
                                                   'type': 'integer'},
                                  'size': {'type': 'integer', 'minimum': 0}},
                   'required': ['session_id', 'buffer_id', 'layout'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.buffer.search_pattern',
  'group': '3.7，缓冲区与网格数据访问 (Buffer & Mesh Data Access)',
  'description': '在 buffer 内搜索字节模式（适用于查找 magic number、NaN pattern、特定 id）。',
  'parameter_raw': 'session_id (string): session_id (str)<br>buffer_id (string): buffer_id '
                   "(str)<br>pattern (string): pattern (str): 支持 hex 字符串（如 'FF 00 ?? 7F'）或 "
                   'base64<br>offset (integer, optional): offset (int, 可选, 默认 0)<br>size (integer, '
                   'optional): size (int, 可选)<br>max_results (integer, optional): max_results '
                   '(int, 可选, 默认 256)',
  'returns_raw': 'ok (bool)<br>data (dict): {matches}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'buffer_id', 'pattern', 'offset', 'size', 'max_results'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'buffer',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'buffer_id': {'description': 'buffer_id (str)', 'type': 'string'},
                                  'pattern': {'description': "pattern (str): 支持 hex 字符串（如 'FF 00 "
                                                             "?? 7F'）或 base64",
                                              'type': 'string'},
                                  'offset': {'description': 'offset (int, 可选, 默认 0)',
                                             'type': 'integer',
                                             'minimum': 0},
                                  'size': {'description': 'size (int, 可选)',
                                           'type': 'integer',
                                           'minimum': 0},
                                  'max_results': {'description': 'max_results (int, 可选, 默认 256)',
                                                  'type': 'integer'}},
                   'required': ['session_id', 'buffer_id', 'pattern'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.capture.close_file',
  'group': '3.2，捕获文件与 Replay Session (Capture & Replay)',
  'description': '关闭捕获文件句柄。',
  'parameter_raw': 'capture_file_id (string): capture_file_id (str)',
  'returns_raw': 'ok (bool)<br>data (dict): tool-specific payload<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['capture_file_id'],
  'prerequisites': [{'requires': 'capture_file_id',
                     'via_tools': ['rd.capture.open_file'],
                     'reason': 'This tool requires an opened capture handle before it can act on '
                               'capture-backed state.'}],
  'namespace': 'capture',
  'input_schema': {'type': 'object',
                   'properties': {'capture_file_id': {'description': 'capture_file_id (str)',
                                                      'type': 'string'}},
                   'required': ['capture_file_id'],
                   'additionalProperties': False},
  'scope': 'global',
  'effects': ['lifecycle'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.capture.close_replay',
  'group': '3.2，捕获文件与 Replay Session (Capture & Replay)',
  'description': '关闭一个 Replay Session，释放回放 driver 与缓存资源。',
  'parameter_raw': 'session_id (string, optional): session_id (str)',
  'returns_raw': 'ok (bool)<br>data (dict): tool-specific payload<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'capture',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'}},
                   'required': [],
                   'additionalProperties': False},
  'scope': 'global',
  'effects': ['lifecycle'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.capture.get_info',
  'group': '3.2，捕获文件与 Replay Session (Capture & Replay)',
  'description': '获取捕获文件元数据（时间、可执行文件、驱动、机器信息、RDC 版本等）。',
  'parameter_raw': 'capture_file_id (string): capture_file_id (str)',
  'returns_raw': 'ok (bool)<br>data (dict): {metadata}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['capture_file_id'],
  'prerequisites': [{'requires': 'capture_file_id',
                     'via_tools': ['rd.capture.open_file'],
                     'reason': 'This tool requires an opened capture handle before it can act on '
                               'capture-backed state.'}],
  'namespace': 'capture',
  'input_schema': {'type': 'object',
                   'properties': {'capture_file_id': {'description': 'capture_file_id (str)',
                                                      'type': 'string'}},
                   'required': ['capture_file_id'],
                   'additionalProperties': False},
  'scope': 'global',
  'effects': ['lifecycle'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.capture.open_file',
  'group': '3.2，捕获文件与 Replay Session (Capture & Replay)',
  'description': '打开一个 .rdc 捕获文件并返回文件句柄（不自动创建 Replay）。',
  'parameter_raw': 'file_path (string): file_path (str): 捕获文件的绝对/可访问路径<br>read_only (boolean, '
                   'optional): read_only (bool, 可选, 默认 true): 是否以只读方式打开',
  'returns_raw': 'ok (bool)<br>data (dict): {capture_file_id, driver}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['file_path', 'read_only'],
  'prerequisites': [],
  'namespace': 'capture',
  'input_schema': {'type': 'object',
                   'properties': {'file_path': {'description': 'file_path (str): 捕获文件的绝对/可访问路径',
                                                'type': 'string'},
                                  'read_only': {'description': 'read_only (bool, 可选, 默认 true): '
                                                               '是否以只读方式打开',
                                                'type': 'boolean'}},
                   'required': ['file_path'],
                   'additionalProperties': False},
  'scope': 'global',
  'effects': ['lifecycle'],
  'evidence_kind': None,
  'path_inputs': [{'name': 'file_path', 'access': 'read'}]},
 {'name': 'rd.capture.open_replay',
  'group': '3.2，捕获文件与 Replay Session (Capture & Replay)',
  'description': '基于 capture_file_id 创建一个可回放的 Replay Session；若提供 options.remote_id，则必须严格走该 live '
                 'remote handle 对应的 remote backend，不允许 silent local fallback。',
  'parameter_raw': 'capture_file_id (string): capture_file_id (str)<br>options (object, optional): '
                   'options (dict, 可选): 回放选项，例如 {force_api?, gpu_id?, software_replay?, '
                   'enable_debug?, replay_cache_mb?}',
  'returns_raw': 'ok (bool)<br>data (dict): {session_id, capture_file_id, frame_count, '
                 'active_event_id, api_properties, recovery_status, reused_session?}<br>artifacts '
                 '(list)<br>error (dict|null): remote handle errors remain explicit; same-context '
                 'live sessions for the same capture are reused with reused_session=true. Stale '
                 'same-capture sessions are cleaned before reopen; cleanup failure returns '
                 'stale_session_requires_restart with recovery steps.<br>meta '
                 '(dict)<br>projections (dict, 可选)',
  'param_names': ['capture_file_id', 'options'],
  'prerequisites': [{'requires': 'capture_file_id',
                     'via_tools': ['rd.capture.open_file'],
                     'reason': 'Opening a replay always requires an opened capture handle.'},
                    {'requires': 'remote_id',
                     'via_tools': ['rd.remote.connect'],
                     'when': 'options.remote_id_present',
                     'reason': 'Remote replay requires a live remote handle in '
                               'options.remote_id.'}],
  'namespace': 'capture',
  'input_schema': {'type': 'object',
                   'properties': {'capture_file_id': {'description': 'capture_file_id (str)',
                                                      'type': 'string'},
                                  'options': {'description': 'options (dict, 可选): 回放选项，例如 '
                                                             '{force_api?, gpu_id?, '
                                                             'software_replay?, enable_debug?, '
                                                             'replay_cache_mb?}',
                                              'type': 'object'}},
                   'required': ['capture_file_id'],
                   'additionalProperties': False},
  'scope': 'global',
  'effects': ['lifecycle'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.core.get_capabilities',
  'group': '3.1，核心与环境管理 (Core & Environment)',
  'description': '获取当前环境能力详情；除 replay/remote/debug 基础项外，还会暴露当前 context/session/backend 视角下的 remote '
                 'capability matrix。',
  'parameter_raw': "detail_level (string, optional): detail_level (str, 可选, 默认 'summary'): "
                   "'summary' | 'full'",
  'returns_raw': 'ok (bool)<br>data (dict): {capabilities}; `capabilities` 至少包含 replay / remote / '
                 'shader_debug / shader_replace / shader_compile / counters / artifact_dir / '
                 'context_id / current_session_id / current_backend，并在 remote 相关场景下附带 '
                 '`remote_capability_matrix`<br>artifacts (list)<br>error (dict|null)<br>meta '
                 '(dict)<br>projections (dict, 可选)',
  'param_names': ['detail_level'],
  'prerequisites': [],
  'namespace': 'core',
  'input_schema': {'type': 'object',
                   'properties': {'detail_level': {'description': 'detail_level (str, 可选, 默认 '
                                                                  "'summary'): 'summary' | 'full'",
                                                   'type': 'string'}},
                   'required': [],
                   'additionalProperties': False},
  'scope': 'global',
  'effects': [],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.core.get_config',
  'group': '3.1，核心与环境管理 (Core & Environment)',
  'description': '读取当前运行时配置。',
  'parameter_raw': '',
  'returns_raw': 'ok (bool)<br>data (dict): {config}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': [],
  'prerequisites': [],
  'namespace': 'core',
  'input_schema': {'type': 'object',
                   'properties': {},
                   'required': [],
                   'additionalProperties': False},
  'scope': 'global',
  'effects': [],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.core.get_logs',
  'group': '3.1，核心与环境管理 (Core & Environment)',
  'description': '读取内部日志（可按时间/级别过滤）。',
  'parameter_raw': 'since_ms (integer, optional): since_ms (int, 可选): 仅返回该时间戳之后的日志<br>level_min '
                   '(string, optional): level_min (str, 可选): 最低级别过滤<br>max_lines (integer, '
                   'optional): max_lines (int, 可选, 默认 500)',
  'returns_raw': 'ok (bool)<br>data (dict): {logs}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['since_ms', 'level_min', 'max_lines'],
  'prerequisites': [],
  'namespace': 'core',
  'input_schema': {'type': 'object',
                   'properties': {'since_ms': {'description': 'since_ms (int, 可选): 仅返回该时间戳之后的日志',
                                               'type': 'integer'},
                                  'level_min': {'description': 'level_min (str, 可选): 最低级别过滤',
                                                'type': 'string'},
                                  'max_lines': {'description': 'max_lines (int, 可选, 默认 500)',
                                                'type': 'integer'}},
                   'required': [],
                   'additionalProperties': False},
  'scope': 'global',
  'effects': [],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.core.get_operation_history',
  'group': '3.1，核心与环境管理 (Core & Environment)',
  'description': '读取当前 context 最近的 trace-linked 操作历史，可按时间、状态与操作名过滤。',
  'parameter_raw': 'since_ms (integer, optional): since_ms (int, 可选): 仅返回该时间戳之后更新过的操作<br>operation '
                   '(string, optional): operation (str, 可选): 按操作名子串过滤<br>status (string, '
                   'optional): status (str, 可选): 按 running/completed/failed 过滤<br>max_items '
                   '(integer, optional): max_items (int, 可选, 默认 32)',
  'returns_raw': 'ok (bool)<br>data (dict): {context_id, operations}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['since_ms', 'operation', 'status', 'max_items'],
  'prerequisites': [],
  'namespace': 'core',
  'input_schema': {'type': 'object',
                   'properties': {'since_ms': {'description': 'since_ms (int, 可选): 仅返回该时间戳之后更新过的操作',
                                               'type': 'integer'},
                                  'operation': {'description': 'operation (str, 可选): 按操作名子串过滤',
                                                'type': 'string'},
                                  'status': {'description': 'status (str, 可选): 按 '
                                                            'running/completed/failed 过滤',
                                             'type': 'string'},
                                  'max_items': {'description': 'max_items (int, 可选, 默认 32)',
                                                'type': 'integer'}},
                   'required': [],
                   'additionalProperties': False},
  'scope': 'global',
  'effects': [],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.core.get_runtime_metrics',
  'group': '3.1，核心与环境管理 (Core & Environment)',
  'description': '读取当前 context 的自监控指标、限制配置、恢复摘要与最近操作统计。',
  'parameter_raw': '',
  'returns_raw': 'ok (bool)<br>data (dict): {context_id, limits, metrics, recovery, '
                 'recent_operations}<br>artifacts (list)<br>error (dict|null)<br>meta '
                 '(dict)<br>projections (dict, 可选)',
  'param_names': [],
  'prerequisites': [],
  'namespace': 'core',
  'input_schema': {'type': 'object',
                   'properties': {},
                   'required': [],
                   'additionalProperties': False},
  'scope': 'global',
  'effects': [],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.core.get_tool_graph',
  'group': '3.1，核心与环境管理 (Core & Environment)',
  'description': '返回 tool 之间的 prerequisite 与 macro-to-canonical 依赖图，图中 nodes 沿用 discovery summary '
                 '与默认排序，帮助 Agent 先看 canonical 主接口，再看 macro 和 navigation 辅助层。',
  'parameter_raw': 'query (string, optional): query (str, 可选)<br>namespace (string, optional): '
                   'namespace (str, 可选)<br>capability (string, optional): capability (str, '
                   '可选)<br>role (string, optional): role (str, 可选): '
                   'canonical|macro|navigation<br>intent (string, optional): intent (str, 可选)',
  'returns_raw': 'ok (bool)<br>data (dict): {tools: discovery summaries with name, namespace, '
                 'group, description, role, discovery_rank, capabilities, intents, prerequisites, '
                 'supports_projection?, recommended_for?, not_primary_for?, edges}<br>artifacts '
                 '(list)<br>error (dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['query', 'namespace', 'capability', 'role', 'intent'],
  'prerequisites': [],
  'namespace': 'core',
  'input_schema': {'type': 'object',
                   'properties': {'query': {'description': 'query (str, 可选)', 'type': 'string'},
                                  'namespace': {'description': 'namespace (str, 可选)',
                                                'type': 'string'},
                                  'capability': {'description': 'capability (str, 可选)',
                                                 'type': 'string'},
                                  'role': {'description': 'role (str, 可选): '
                                                          'canonical|macro|navigation',
                                           'type': 'string'},
                                  'intent': {'description': 'intent (str, 可选)', 'type': 'string'}},
                   'required': [],
                   'additionalProperties': False},
  'scope': 'global',
  'effects': [],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.core.get_version',
  'group': '3.1，核心与环境管理 (Core & Environment)',
  'description': '获取 RenderDoc 运行时版本与构建信息。',
  'parameter_raw': '',
  'returns_raw': 'ok (bool)<br>data (dict): {version, commit_hash, build_date}<br>artifacts '
                 '(list)<br>error (dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': [],
  'prerequisites': [],
  'namespace': 'core',
  'input_schema': {'type': 'object',
                   'properties': {},
                   'required': [],
                   'additionalProperties': False},
  'scope': 'global',
  'effects': [],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.core.healthcheck',
  'group': '3.1，核心与环境管理 (Core & Environment)',
  'description': '执行自检：验证 RenderDoc 库加载、临时目录写入、（可选）创建最小 Replay/Remote 连接等。',
  'parameter_raw': 'check_remote (boolean, optional): check_remote (bool, 可选, 默认 '
                   'false)<br>check_replay (boolean, optional): check_replay (bool, 可选, 默认 true)',
  'returns_raw': 'ok (bool)<br>data (dict): {checks}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['check_remote', 'check_replay'],
  'prerequisites': [],
  'namespace': 'core',
  'input_schema': {'type': 'object',
                   'properties': {'check_remote': {'description': 'check_remote (bool, 可选, 默认 '
                                                                  'false)',
                                                   'type': 'boolean'},
                                  'check_replay': {'description': 'check_replay (bool, 可选, 默认 '
                                                                  'true)',
                                                   'type': 'boolean'}},
                   'required': [],
                   'additionalProperties': False},
  'scope': 'global',
  'effects': [],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.core.init',
  'group': '3.1，核心与环境管理 (Core & Environment)',
  'description': '初始化 RenderDoc Replay/Remote 运行时；建立对象池与临时目录；必须在首次使用前调用一次。',
  'parameter_raw': 'global_env (object, optional): global_env (dict, 可选): 全局配置，例如 {temp_dir, '
                   'artifact_dir, log_level, replay_cache_size_mb}<br>enable_remote (boolean, '
                   'optional): enable_remote (bool, 可选, 默认 true): 是否启用 rd.remote.*',
  'returns_raw': 'ok (bool)<br>data (dict): {api_version, capabilities}<br>artifacts '
                 '(list)<br>error (dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['global_env', 'enable_remote'],
  'prerequisites': [],
  'namespace': 'core',
  'input_schema': {'type': 'object',
                   'properties': {'global_env': {'description': 'global_env (dict, 可选): 全局配置，例如 '
                                                                '{temp_dir, artifact_dir, '
                                                                'log_level, replay_cache_size_mb}',
                                                 'type': 'object'},
                                  'enable_remote': {'description': 'enable_remote (bool, 可选, 默认 '
                                                                   'true): 是否启用 rd.remote.*',
                                                    'type': 'boolean'}},
                   'required': [],
                   'additionalProperties': False},
  'scope': 'global',
  'effects': ['global_config'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.core.list_tools',
  'group': '3.1，核心与环境管理 (Core & Environment)',
  'description': '按 namespace、group、capability、role、intent 等结构化条件列出可用 tool，默认仍以 canonical `rd.*` '
                 '主接口优先，其后才是 macro、session/context/core 元信息层与 navigation 辅助层。',
  'parameter_raw': 'namespace (string, optional): namespace (str, 可选)<br>group (string, optional): '
                   'group (str, 可选)<br>capability (string, optional): capability (str, 可选)<br>role '
                   '(string, optional): role (str, 可选): canonical|macro|navigation<br>intent '
                   '(string, optional): intent (str, 可选)<br>mutates_state (boolean, optional): '
                   'mutates_state (bool, 可选)<br>detail_level (string, optional): detail_level '
                   "(str, 可选, 默认 'summary'): summary|full<br>query (string, optional): Filter "
                   'names and descriptions.',
  'returns_raw': 'ok (bool)<br>data (dict): {tool_count, tools: discovery summaries with name, '
                 'namespace, group, description, role, discovery_rank, capabilities, intents, '
                 'prerequisites, supports_projection?, recommended_for?, '
                 'not_primary_for?}<br>artifacts (list)<br>error (dict|null)<br>meta '
                 '(dict)<br>projections (dict, 可选)',
  'param_names': ['namespace',
                  'group',
                  'capability',
                  'role',
                  'intent',
                  'mutates_state',
                  'detail_level',
                  'query'],
  'prerequisites': [],
  'namespace': 'core',
  'input_schema': {'type': 'object',
                   'properties': {'namespace': {'description': 'namespace (str, 可选)',
                                                'type': 'string'},
                                  'group': {'description': 'group (str, 可选)', 'type': 'string'},
                                  'capability': {'description': 'capability (str, 可选)',
                                                 'type': 'string'},
                                  'role': {'description': 'role (str, 可选): '
                                                          'canonical|macro|navigation',
                                           'type': 'string'},
                                  'intent': {'description': 'intent (str, 可选)', 'type': 'string'},
                                  'mutates_state': {'description': 'mutates_state (bool, 可选)',
                                                    'type': 'boolean'},
                                  'detail_level': {'description': 'detail_level (str, 可选, 默认 '
                                                                  "'summary'): summary|full",
                                                   'type': 'string'},
                                  'query': {'type': 'string',
                                            'description': 'Filter names and descriptions.'}},
                   'required': [],
                   'additionalProperties': False},
  'scope': 'global',
  'effects': [],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.core.set_config',
  'group': '3.1，核心与环境管理 (Core & Environment)',
  'description': '设置运行时配置（对后续调用生效）。',
  'parameter_raw': 'config (object): config (dict): {artifact_dir?, temp_dir?, '
                   'max_artifact_bytes?, default_image_format?, default_mesh_format?, log_level?}',
  'returns_raw': 'ok (bool)<br>data (dict): {applied}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['config'],
  'prerequisites': [],
  'namespace': 'core',
  'input_schema': {'type': 'object',
                   'properties': {'config': {'description': 'config (dict): {artifact_dir?, '
                                                            'temp_dir?, max_artifact_bytes?, '
                                                            'default_image_format?, '
                                                            'default_mesh_format?, log_level?}',
                                             'type': 'object'}},
                   'required': ['config'],
                   'additionalProperties': False},
  'scope': 'global',
  'effects': ['global_config'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.core.set_log_level',
  'group': '3.1，核心与环境管理 (Core & Environment)',
  'description': '设置内部日志等级，便于定位 CLI runtime 与 RenderDoc 侧错误。',
  'parameter_raw': "level (string): level (str): 'trace'|'debug'|'info'|'warn'|'error'",
  'returns_raw': 'ok (bool)<br>data (dict): tool-specific payload<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['level'],
  'prerequisites': [],
  'namespace': 'core',
  'input_schema': {'type': 'object',
                   'properties': {'level': {'description': 'level (str): '
                                                           "'trace'|'debug'|'info'|'warn'|'error'",
                                            'type': 'string'}},
                   'required': ['level'],
                   'additionalProperties': False},
  'scope': 'global',
  'effects': ['global_config'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.core.shutdown',
  'group': '3.1，核心与环境管理 (Core & Environment)',
  'description': '关闭运行时并释放所有资源（Replay Session、Remote 连接、临时文件句柄）。',
  'parameter_raw': '',
  'returns_raw': 'ok (bool)<br>data (dict): {released}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': [],
  'prerequisites': [],
  'namespace': 'core',
  'input_schema': {'type': 'object',
                   'properties': {},
                   'required': [],
                   'additionalProperties': False},
  'scope': 'global',
  'effects': ['global_config'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.debug.clear_breakpoints',
  'group': '3.9，Shader Debugger 与像素/顶点级调试 (Shader Debugging)',
  'description': '清除所有断点。',
  'parameter_raw': 'session_id (string): session_id (str)<br>shader_debug_id (string): '
                   'shader_debug_id (str)',
  'returns_raw': 'ok (bool)<br>data (dict): tool-specific payload<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'shader_debug_id'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'debug',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'shader_debug_id': {'description': 'shader_debug_id (str)',
                                                      'type': 'string'}},
                   'required': ['session_id', 'shader_debug_id'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['shader_debug', 'replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.debug.continue',
  'group': '3.9，Shader Debugger 与像素/顶点级调试 (Shader Debugging)',
  'description': '继续执行 debugger（直到断点/结束/超时）。',
  'parameter_raw': 'session_id (string): session_id (str)<br>shader_debug_id (string): '
                   'shader_debug_id (str)<br>timeout_ms (integer, optional): timeout_ms (int, 可选, '
                   '默认 10000)',
  'returns_raw': 'ok (bool)<br>data (dict): {state, stopped_reason}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'shader_debug_id', 'timeout_ms'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'debug',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'shader_debug_id': {'description': 'shader_debug_id (str)',
                                                      'type': 'string'},
                                  'timeout_ms': {'description': 'timeout_ms (int, 可选, 默认 10000)',
                                                 'type': 'integer'}},
                   'required': ['session_id', 'shader_debug_id'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['shader_debug', 'replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.debug.evaluate_expression',
  'group': '3.9，Shader Debugger 与像素/顶点级调试 (Shader Debugging)',
  'description': "在 debugger 上下文中求值表达式（如 'cb0.myVar' 或寄存器表达式；实现可选）。",
  'parameter_raw': 'session_id (string): session_id (str)<br>shader_debug_id (string): '
                   'shader_debug_id (str)<br>expression (string): expression (str)',
  'returns_raw': 'ok (bool)<br>data (dict): {value}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'shader_debug_id', 'expression'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'debug',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'shader_debug_id': {'description': 'shader_debug_id (str)',
                                                      'type': 'string'},
                                  'expression': {'description': 'expression (str)',
                                                 'type': 'string'}},
                   'required': ['session_id', 'shader_debug_id', 'expression'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['shader_debug', 'replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.debug.finish',
  'group': '3.9，Shader Debugger 与像素/顶点级调试 (Shader Debugging)',
  'description': '结束并释放 shader debug session。',
  'parameter_raw': 'session_id (string): session_id (str)<br>shader_debug_id (string): '
                   'shader_debug_id (str)',
  'returns_raw': 'ok (bool)<br>data (dict): tool-specific payload<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'shader_debug_id'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'debug',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'shader_debug_id': {'description': 'shader_debug_id (str)',
                                                      'type': 'string'}},
                   'required': ['session_id', 'shader_debug_id'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['shader_debug', 'replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.debug.get_callstack',
  'group': '3.9，Shader Debugger 与像素/顶点级调试 (Shader Debugging)',
  'description': '获取 shader 调用栈（函数名/文件/行）。',
  'parameter_raw': 'session_id (string): session_id (str)<br>shader_debug_id (string): '
                   'shader_debug_id (str)',
  'returns_raw': 'ok (bool)<br>data (dict): {callstack}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'shader_debug_id'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'debug',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'shader_debug_id': {'description': 'shader_debug_id (str)',
                                                      'type': 'string'}},
                   'required': ['session_id', 'shader_debug_id'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['shader_debug', 'replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.debug.get_variables',
  'group': '3.9，Shader Debugger 与像素/顶点级调试 (Shader Debugging)',
  'description': '获取当前 scope 的变量（支持按名称过滤/按路径展开结构体）。',
  'parameter_raw': 'session_id (string): session_id (str)<br>shader_debug_id (string): '
                   'shader_debug_id (str)<br>name_filter (string, optional): name_filter (str, '
                   '可选): regex/contains<br>expand_depth (integer, optional): expand_depth (int, '
                   '可选, 默认 2)<br>max_variables (integer, optional): max_variables (int, 可选, 默认 '
                   '2048)',
  'returns_raw': 'ok (bool)<br>data (dict): {variables}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'shader_debug_id', 'name_filter', 'expand_depth', 'max_variables'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'debug',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'shader_debug_id': {'description': 'shader_debug_id (str)',
                                                      'type': 'string'},
                                  'name_filter': {'description': 'name_filter (str, 可选): '
                                                                 'regex/contains',
                                                  'type': 'string'},
                                  'expand_depth': {'description': 'expand_depth (int, 可选, 默认 2)',
                                                   'type': 'integer'},
                                  'max_variables': {'description': 'max_variables (int, 可选, 默认 '
                                                                   '2048)',
                                                    'type': 'integer'}},
                   'required': ['session_id', 'shader_debug_id'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['shader_debug', 'replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.debug.run_to',
  'group': '3.9，Shader Debugger 与像素/顶点级调试 (Shader Debugging)',
  'description': '运行到指定位置（PC 或 source location）。',
  'parameter_raw': 'session_id (string): session_id (str)<br>shader_debug_id (string): '
                   'shader_debug_id (str)<br>target (object): See input_schema for '
                   'constraints.<br>timeout_ms (integer, optional): timeout_ms (int, 可选, 默认 10000)',
  'returns_raw': 'ok (bool)<br>data (dict): {state}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'shader_debug_id', 'target', 'timeout_ms'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'debug',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'shader_debug_id': {'description': 'shader_debug_id (str)',
                                                      'type': 'string'},
                                  'target': {'type': 'object',
                                             'properties': {'texture_id': {'type': 'string'},
                                                            'rt_index': {'type': 'integer',
                                                                         'minimum': 0}},
                                             'additionalProperties': False},
                                  'timeout_ms': {'description': 'timeout_ms (int, 可选, 默认 10000)',
                                                 'type': 'integer'}},
                   'required': ['session_id', 'shader_debug_id', 'target'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['shader_debug', 'replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.debug.set_breakpoints',
  'group': '3.9，Shader Debugger 与像素/顶点级调试 (Shader Debugging)',
  'description': '设置断点列表（按 PC 或 source location）。',
  'parameter_raw': 'session_id (string): session_id (str)<br>shader_debug_id (string): '
                   'shader_debug_id (str)<br>breakpoints (array): breakpoints (list[dict]): {pc?, '
                   'file?, line?}',
  'returns_raw': 'ok (bool)<br>data (dict): {active_breakpoints}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'shader_debug_id', 'breakpoints'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'debug',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'shader_debug_id': {'description': 'shader_debug_id (str)',
                                                      'type': 'string'},
                                  'breakpoints': {'description': 'breakpoints (list[dict]): {pc?, '
                                                                 'file?, line?}',
                                                  'type': 'array',
                                                  'items': {}}},
                   'required': ['session_id', 'shader_debug_id', 'breakpoints'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['shader_debug', 'replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.debug.step',
  'group': '3.9，Shader Debugger 与像素/顶点级调试 (Shader Debugging)',
  'description': '单步执行 debugger（步进一条指令或源代码行）。',
  'parameter_raw': 'session_id (string): session_id (str)<br>shader_debug_id (string): '
                   'shader_debug_id (str)<br>step_mode (string, optional): step_mode (str, 可选, 默认 '
                   "'instruction'): 'instruction' | 'line' | 'over' | 'out'",
  'returns_raw': 'ok (bool)<br>data (dict): {state}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'shader_debug_id', 'step_mode'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'debug',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'shader_debug_id': {'description': 'shader_debug_id (str)',
                                                      'type': 'string'},
                                  'step_mode': {'description': 'step_mode (str, 可选, 默认 '
                                                               "'instruction'): 'instruction' | "
                                                               "'line' | 'over' | 'out'",
                                                'type': 'string'}},
                   'required': ['session_id', 'shader_debug_id'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['shader_debug', 'replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.diag.scan_common_issues',
  'group': '3.14，诊断工具 (Diagnostics, Heuristic Checks)',
  'description': '对当前 active event 执行一组常见问题扫描（空绑定、viewport/scissor、depth/blend、格式不匹配等），输出结构化 issue '
                 '列表。',
  'parameter_raw': 'session_id (string): session_id (str)<br>severity_min (string, optional): '
                   "severity_min (str, 可选, 默认 'info')<br>include_suggestions (boolean, optional): "
                   'include_suggestions (bool, 可选, 默认 true)',
  'returns_raw': 'ok (bool)<br>data (dict): {issues}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'severity_min', 'include_suggestions'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'diag',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'severity_min': {'description': 'severity_min (str, 可选, 默认 '
                                                                  "'info')",
                                                   'type': 'string'},
                                  'include_suggestions': {'description': 'include_suggestions '
                                                                         '(bool, 可选, 默认 true)',
                                                          'type': 'boolean'}},
                   'required': ['session_id'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.event.diff_pipeline_state',
  'group': '3.3，事件导航与 API 检查 (Event Navigation & API Inspection)',
  'description': '对比两个 Event 的 Pipeline State 差异，可用于定位“状态被谁修改”的问题。',
  'parameter_raw': 'session_id (string): session_id (str)<br>event_a (integer): event_a (int): 基准 '
                   'eventId<br>event_b (integer): event_b (int): 对比 eventId<br>scope (string, '
                   "optional): scope (str, 可选, 默认 'all'): 对比范围，可选值 'all', 'shaders', 'bindings', "
                   "'raster', 'om', 'ia'<br>include_unchanged (boolean, optional): "
                   'include_unchanged (bool, 可选, 默认 false)',
  'returns_raw': 'ok (bool)<br>data (dict): {diff}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'event_a', 'event_b', 'scope', 'include_unchanged'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'event',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'event_a': {'description': 'event_a (int): 基准 eventId',
                                              'type': 'integer'},
                                  'event_b': {'description': 'event_b (int): 对比 eventId',
                                              'type': 'integer'},
                                  'scope': {'description': "scope (str, 可选, 默认 'all'): 对比范围，可选值 "
                                                           "'all', 'shaders', 'bindings', "
                                                           "'raster', 'om', 'ia'",
                                            'type': 'string'},
                                  'include_unchanged': {'description': 'include_unchanged (bool, '
                                                                       '可选, 默认 false)',
                                                        'type': 'boolean'}},
                   'required': ['session_id', 'event_a', 'event_b'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.event.get_action_details',
  'group': '3.3，事件导航与 API 检查 (Event Navigation & API Inspection)',
  'description': '获取单个 Action 的详细信息，包括 Drawcall 参数、Marker 范围以及输出目标等摘要。',
  'parameter_raw': 'session_id (string): session_id (str)<2>event_id (int)<br>event_id (integer, '
                   'optional): See input_schema for constraints.',
  'returns_raw': 'Returns parent_chain, nullable marker_path and depth_output; ResourceId is local to this capture.<br>ok (bool)<br>data (dict): {action}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'event_id'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'event',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)<2>event_id (int)',
                                                 'type': 'string'},
                                  'event_id': {'type': 'integer', 'minimum': 0}},
                   'required': ['session_id'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.event.get_action_tree',
  'group': '3.3，事件导航与 API 检查 (Event Navigation & API Inspection)',
  'description': '获取当前帧完整的 Action 树，支持按深度或过滤条件进行裁剪。',
  'parameter_raw': 'session_id (string): session_id (str)<br>max_depth (integer, optional): '
                   'max_depth (int, 可选)<br>filter (object, optional): See input_schema for '
                   'constraints.<br>offset (integer, optional): offset (int, 可选, 默认 0): '
                   '根节点分页偏移<br>limit (integer, optional): limit (int, 可选, 默认 256): '
                   '根节点分页大小<br>max_nodes (integer, optional): max_nodes (int, 可选, 默认 2000): '
                   '整棵树返回的最大节点数<br>event_id (integer, optional): See input_schema for '
                   'constraints.<br>include_markers (boolean, optional): See input_schema for '
                   'constraints.<br>include_drawcalls (boolean, optional): See input_schema for '
                   'constraints.<br>projection (object, optional): See input_schema for '
                   'constraints.',
  'returns_raw': 'ok (bool)<br>data (dict): {root, pagination}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id',
                  'max_depth',
                  'filter',
                  'offset',
                  'limit',
                  'max_nodes',
                  'event_id',
                  'include_markers',
                  'include_drawcalls',
                  'projection'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'event',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'max_depth': {'description': 'max_depth (int, 可选)',
                                                'type': 'integer'},
                                  'filter': {'type': 'object',
                                             'properties': {'name_contains': {'type': 'string',
                                                                              'description': 'Case-insensitive '
                                                                                             'substring '
                                                                                             'match '
                                                                                             'against '
                                                                                             'action '
                                                                                             'names.'}},
                                             'additionalProperties': False},
                                  'offset': {'description': 'offset (int, 可选, 默认 0): 根节点分页偏移',
                                             'type': 'integer',
                                             'minimum': 0},
                                  'limit': {'description': 'limit (int, 可选, 默认 256): 根节点分页大小',
                                            'type': 'integer',
                                            'minimum': 1},
                                  'max_nodes': {'description': 'max_nodes (int, 可选, 默认 2000): '
                                                               '整棵树返回的最大节点数',
                                                'type': 'integer',
                                                'minimum': 1},
                                  'event_id': {'type': 'integer', 'minimum': 0},
                                  'include_markers': {'type': 'boolean', 'default': True},
                                  'include_drawcalls': {'type': 'boolean', 'default': True},
                                  'projection': {'type': 'object',
                                                 'properties': {'kind': {'type': 'string',
                                                                         'enum': ['tabular']},
                                                                'include_tsv_text': {'type': 'boolean'}},
                                                 'required': ['kind'],
                                                 'additionalProperties': False}},
                   'required': ['session_id'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'supports_projection': {'tabular': True},
  'path_inputs': []},
 {'name': 'rd.event.get_active',
  'group': '3.2，捕获文件与 Replay Session (Capture & Replay)',
  'description': '读取当前 active event。',
  'parameter_raw': 'session_id (string): session_id (str)',
  'returns_raw': 'ok (bool)<br>data (dict): {active_event_id}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'event',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'}},
                   'required': ['session_id'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.event.get_callstack',
  'group': '3.3，事件导航与 API 检查 (Event Navigation & API Inspection)',
  'description': '获取指定 Event 的 CPU Callstack（如果捕获时包含该信息且平台支持）。',
  'parameter_raw': 'session_id (string): session_id (str)<br>event_id (integer): event_id '
                   '(int)<br>resolve_symbols (boolean, optional): resolve_symbols (bool, 可选, 默认 '
                   'false)',
  'returns_raw': 'ok (bool)<br>data (dict): {callstack}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'event_id', 'resolve_symbols'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'event',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'event_id': {'description': 'event_id (int)',
                                               'type': 'integer',
                                               'minimum': 0},
                                  'resolve_symbols': {'description': 'resolve_symbols (bool, 可选, '
                                                                     '默认 false)',
                                                      'type': 'boolean'}},
                   'required': ['session_id', 'event_id'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.event.get_parent_chain',
  'group': '3.3，事件导航与 API 检查 (Event Navigation & API Inspection)',
  'description': '获取指定 Event 的父链（从根节点到当前 Event），用于还原 Marker Stack 或 Pass 层级。',
  'parameter_raw': 'session_id (string): session_id (str)<br>event_id (integer): event_id (int)',
  'returns_raw': 'ok (bool)<br>data (dict): {parent_chain}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'event_id'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'event',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'event_id': {'description': 'event_id (int)',
                                               'type': 'integer',
                                               'minimum': 0}},
                   'required': ['session_id', 'event_id'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.event.get_resource_usage',
  'group': '3.3，事件导航与 API 检查 (Event Navigation & API Inspection)',
  'description': '获取指定 Event 上资源的摘要使用情况，例如哪些资源被绑定为 RT/DS/SRV/UAV/CBV/IB/VB 等。',
  'parameter_raw': 'session_id (string): session_id (str)<br>event_id (integer): event_id (int)',
  'returns_raw': 'ok (bool)<br>data (dict): {usage}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'event_id'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'event',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'event_id': {'description': 'event_id (int)',
                                               'type': 'integer',
                                               'minimum': 0}},
                   'required': ['session_id', 'event_id'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.event.list_passes',
  'group': '3.3，事件导航与 API 检查 (Event Navigation & API Inspection)',
  'description': '根据 Marker 或 Region 归纳当前帧的 Pass 列表，类似于 RenderDoc Event Browser 的 Region 视图。',
  'parameter_raw': 'session_id (string): session_id (str)<br>marker_policy (string, optional): '
                   "marker_policy (str, 可选, 默认 'region'): 可选值 'region', 'markers_only', 'both'",
  'returns_raw': 'ok (bool)<br>data (dict): {passes}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'marker_policy'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'event',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'marker_policy': {'description': 'marker_policy (str, 可选, 默认 '
                                                                   "'region'): 可选值 'region', "
                                                                   "'markers_only', 'both'",
                                                    'type': 'string'}},
                   'required': ['session_id'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.event.search_actions',
  'group': '3.3，事件导航与 API 检查 (Event Navigation & API Inspection)',
  'description': '在当前帧的 Action 树中搜索节点，支持按名称、Flag 或事件范围等条件。',
  'parameter_raw': 'session_id (string): session_id (str)<br>query (object): query (dict): 查询条件，例如 '
                   '{name_regex?, name_contains?, flags_include?, flags_exclude?, event_id_min?, '
                   'event_id_max?}<br>max_results (integer, optional): max_results (int, 可选, 默认 '
                   '200)',
  'returns_raw': 'ok (bool)<br>data (dict): {matches}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'query', 'max_results'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'event',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'query': {'description': 'query (dict): 查询条件，例如 {name_regex?, '
                                                           'name_contains?, flags_include?, '
                                                           'flags_exclude?, event_id_min?, '
                                                           'event_id_max?}',
                                            'type': 'object'},
                                  'max_results': {'description': 'max_results (int, 可选, 默认 200)',
                                                  'type': 'integer'}},
                   'required': ['session_id', 'query'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.event.set_active',
  'group': '3.2，捕获文件与 Replay Session (Capture & Replay)',
  'description': '设置当前 active event；成功后 runtime 与 context snapshot 必须同步到同一个 resolved '
                 'event，失败时保持旧状态不变。',
  'parameter_raw': 'session_id (string): session_id (str)<br>event_id (integer): event_id (int)',
  'returns_raw': 'ok (bool)<br>data (dict): {active_event_id}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'event_id'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'event',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'event_id': {'description': 'event_id (int)',
                                               'type': 'integer',
                                               'minimum': 0}},
                   'required': ['session_id', 'event_id'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.export.buffer',
  'group': '3.11，导出、报告与可复现打包 (Export & Reporting)',
  'description': '将 buffer 内容导出到文件；这是统一的 buffer 落盘导出入口。',
  'parameter_raw': 'session_id (string): session_id (str)<br>buffer_id (string): buffer_id '
                   '(str)<br>output_path (string): output_path (str)<br>offset (integer, '
                   'optional): offset (int, 可选, 默认 0)<br>size (integer, optional): size (int, 可选)',
  'returns_raw': 'ok (bool)<br>data (dict): {saved_path}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'buffer_id', 'output_path', 'offset', 'size'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'export',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'buffer_id': {'description': 'buffer_id (str)', 'type': 'string'},
                                  'output_path': {'description': 'output_path (str)',
                                                  'type': 'string'},
                                  'offset': {'description': 'offset (int, 可选, 默认 0)',
                                             'type': 'integer',
                                             'minimum': 0},
                                  'size': {'description': 'size (int, 可选)',
                                           'type': 'integer',
                                           'minimum': 0}},
                   'required': ['session_id', 'buffer_id', 'output_path'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position', 'artifact_write'],
  'evidence_kind': None,
  'path_inputs': [{'name': 'output_path', 'access': 'write'}]},
 {'name': 'rd.export.cbuffer_dump',
  'group': '3.11，导出、报告与可复现打包 (Export & Reporting)',
  'description': '导出当前 event 的常量缓冲数据（按 stage/slot 命名），支持结构化变量值。',
  'parameter_raw': 'session_id (string): session_id (str)<br>output_dir (string): output_dir '
                   '(str)<br>stages (array, optional): stages (list[str], 可选, 默认 '
                   "['vs','ps','cs'])<br>slots (array, optional): slots (list[int], "
                   '可选)<br>max_bytes (integer, optional): max_bytes (int, 可选, 默认 '
                   '1048576)<br>include_raw (boolean, optional): include_raw (bool, 可选, 默认 '
                   'false)<br>include_decoded (boolean, optional): include_decoded (bool, 可选, 默认 '
                   'true)',
  'returns_raw': 'ok (bool)<br>data (dict): {dumped_paths, saved_files, failures, partial, stages, '
                 'slots}; each stage/slot is handled independently and partial failures are '
                 'recorded instead of blocking the whole request.<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id',
                  'output_dir',
                  'stages',
                  'slots',
                  'max_bytes',
                  'include_raw',
                  'include_decoded'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'export',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'output_dir': {'description': 'output_dir (str)',
                                                 'type': 'string'},
                                  'stages': {'description': 'stages (list[str], 可选, 默认 '
                                                            "['vs','ps','cs'])",
                                             'type': 'array',
                                             'items': {'type': 'string'}},
                                  'slots': {'description': 'slots (list[int], 可选)',
                                            'type': 'array',
                                            'items': {}},
                                  'max_bytes': {'description': 'max_bytes (int, 可选, 默认 1048576)',
                                                'type': 'integer'},
                                  'include_raw': {'description': 'include_raw (bool, 可选, 默认 false)',
                                                  'type': 'boolean'},
                                  'include_decoded': {'description': 'include_decoded (bool, 可选, '
                                                                     '默认 true)',
                                                      'type': 'boolean'}},
                   'required': ['session_id', 'output_dir'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position', 'artifact_write'],
  'evidence_kind': None,
  'path_inputs': [{'name': 'output_dir', 'access': 'write'}]},
 {'name': 'rd.export.mesh',
  'group': '3.11，导出、报告与可复现打包 (Export & Reporting)',
  'description': 'Export post-VS positions or explicit VS input position/normal/UV as Wavefront OBJ. Supports '
                 'float32 positions and triangle list/strip, line list or point list topology; '
                 'VS input attributes require float semantics in original input space; postvs remains positions only.',
  'parameter_raw': 'session_id (string), output_path (string), event_id (integer, optional), '
                   'format=obj, space=postvs|vs_input, include_attributes=false|true (true requires vs_input)',
  'returns_raw': 'JSON declares exported attributes. VS input with include_attributes=true exports v/vt/vn with matching face indices; postvs is positions only.<br>data: '
                 '{saved_path,export_format,space,include_attributes,resolved_event_id,vertex_count,primitive_count}. '
                 'Unsupported geometry produces mesh_export_unsupported; no placeholder file is '
                 'written.',
  'param_names': ['session_id', 'event_id', 'format', 'output_path', 'include_attributes', 'space'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'export',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'event_id': {'description': 'event_id (int, 可选)',
                                               'type': 'integer',
                                               'minimum': 0},
                                  'format': {'type': 'string', 'enum': ['obj'], 'default': 'obj'},
                                  'output_path': {'description': 'output_path (str)',
                                                  'type': 'string'},
                                  'include_attributes': {'type': 'boolean',
                                                                                                                  'default': False},
                                  'space': {'type': 'string',
                                            'enum': ['postvs', 'vs_input'],
                                            'default': 'postvs'}},
                   'required': ['session_id', 'output_path'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position', 'artifact_write'],
  'evidence_kind': None,
  'path_inputs': [{'name': 'output_path', 'access': 'write'}]},
 {'name': 'rd.export.screenshot',
  'group': '3.11，导出、报告与可复现打包 (Export & Reporting)',
  'description': '导出当前 event 的输出截图（等价于 UI 的保存 framebuffer）。',
  'parameter_raw': 'session_id (string): session_id (str)<br>target (object, optional): See '
                   'input_schema for constraints.<br>event_id (integer, optional): event_id (int, '
                   '可选): 指定 event 输出；缺省为当前 active event<br>output_path (string): output_path '
                   '(str)<br>file_format (string, optional): file_format (str, 可选, 默认 '
                   "'png')<br>include_alpha (boolean, optional): include_alpha (bool, 可选, 默认 "
                   'true)<br>overlay (string, optional): overlay (str, 可选): '
                   "'None'|'Drawcall'|'Wireframe'|'Overdraw'",
  'returns_raw': 'ok (bool)<br>data (dict): single export returns {artifact_path, saved_path, '
                 'image_path, meta, resolved_event_id, selected_formats, requested_formats, '
                 'recommended_formats, name_info, texture_format, chosen_output_slot, texture_id, '
                 'target_source, binding_truth_level, visual_truth_level, evidence_truth_level, '
                 'summary_degraded_reasons}; multi-format export returns {exports, saved_paths, '
                 'image_paths, resolved_event_id, selected_formats, requested_formats, '
                 'recommended_formats, name_info, texture_format, chosen_output_slot, texture_id, '
                 'target_source, binding_truth_level, visual_truth_level, evidence_truth_level, '
                 'summary_degraded_reasons}<br>artifacts (list)<br>error (dict|null)<br>meta '
                 '(dict)<br>projections (dict, 可选)',
  'param_names': ['session_id',
                  'target',
                  'event_id',
                  'output_path',
                  'file_format',
                  'include_alpha',
                  'overlay'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'export',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'target': {'type': 'object',
                                             'properties': {'texture_id': {'type': 'string'},
                                                            'rt_index': {'type': 'integer',
                                                                         'minimum': 0}},
                                             'additionalProperties': False},
                                  'event_id': {'description': 'event_id (int, 可选): 指定 event '
                                                              '输出；缺省为当前 active event',
                                               'type': 'integer',
                                               'minimum': 0},
                                  'output_path': {'description': 'output_path (str)',
                                                  'type': 'string'},
                                  'file_format': {'description': "file_format (str, 可选, 默认 'png')",
                                                  'type': 'string'},
                                  'include_alpha': {'description': 'include_alpha (bool, 可选, 默认 '
                                                                   'true)',
                                                    'type': 'boolean'},
                                  'overlay': {'description': 'overlay (str, 可选): '
                                                             "'None'|'Drawcall'|'Wireframe'|'Overdraw'",
                                              'type': 'string'}},
                   'required': ['session_id', 'output_path'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position', 'artifact_write'],
  'evidence_kind': 'measurement',
  'path_inputs': [{'name': 'output_path', 'access': 'write'}]},
 {'name': 'rd.export.shader_bundle',
  'group': '3.11，导出、报告与可复现打包 (Export & Reporting)',
  'description': '导出当前 event 相关 shader 的 bundle；event-bound shader 绑定与 `rd.pipeline.get_shader` / '
                 '`rd.shader.get_disassembly` / `rd.shader.get_reflection` / '
                 '`rd.shader.edit_and_replace` 保持一致。',
  'parameter_raw': 'session_id (string): session_id (str)<br>event_id (integer, optional): '
                   'event_id (int, 可选)<br>output_dir (string): output_dir '
                   '(str)<br>include_binaries (boolean, optional): include_binaries (bool, 可选, 默认 '
                   'true)<br>include_reflection (boolean, optional): include_reflection (bool, 可选, '
                   '默认 true)<br>include_disassembly (boolean, optional): include_disassembly '
                   '(bool, 可选, 默认 true)',
  'returns_raw': 'ok (bool)<br>data (dict): {output_dir, bundle_path, '
                 'resolved_event_id}<br>artifacts (list)<br>error (dict|null): 当请求 event 没有可绑定 '
                 'shader 时，显式返回 `shader_bundle_empty`<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id',
                  'event_id',
                  'output_dir',
                  'include_binaries',
                  'include_reflection',
                  'include_disassembly'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'export',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'event_id': {'description': 'event_id (int, 可选)',
                                               'type': 'integer',
                                               'minimum': 0},
                                  'output_dir': {'description': 'output_dir (str)',
                                                 'type': 'string'},
                                  'include_binaries': {'description': 'include_binaries (bool, 可选, '
                                                                      '默认 true)',
                                                       'type': 'boolean'},
                                  'include_reflection': {'description': 'include_reflection (bool, '
                                                                        '可选, 默认 true)',
                                                         'type': 'boolean'},
                                  'include_disassembly': {'description': 'include_disassembly '
                                                                         '(bool, 可选, 默认 true)',
                                                          'type': 'boolean'}},
                   'required': ['session_id', 'output_dir'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position', 'artifact_write'],
  'evidence_kind': None,
  'path_inputs': [{'name': 'output_dir', 'access': 'write'}]},
 {'name': 'rd.export.texture',
  'group': '3.11，导出、报告与可复现打包 (Export & Reporting)',
  'description': '将纹理导出为可直接打开的图片/导出文件；这是统一的纹理导出入口，支持子资源选择、显示映射与通道控制。',
  'parameter_raw': 'session_id (string): session_id (str)<br>texture_id (string): texture_id '
                   '(str)<br>subresource (object, optional): See input_schema for '
                   'constraints.<br>output_path (string): output_path (str)<br>file_format '
                   "(string, optional): file_format (str, 可选, 默认 'png'): canonical output format; "
                   "high precision formats such as 'hdr'/'exr' fail closed if "
                   'unavailable<br>channels (string, optional): channels (str, 可选, 默认 '
                   "'rgba')<br>remap (object, optional): remap (dict, 可选): {black_point, "
                   'white_point, gamma, hdr_clamp?}<br>flip_y (boolean, optional): flip_y (bool, '
                   '可选, 默认 false)',
  'returns_raw': 'ok (bool)<br>data (dict): {artifact_path, saved_path, meta, selected_formats, '
                 'requested_formats, recommended_formats, name_info, texture_format}; multi-format '
                 'export returns {exports, saved_paths, selected_formats, requested_formats, '
                 'recommended_formats}. Explicit HDR/EXR/DDS requests never silently downgrade to '
                 'PNG; unavailable encoders return ok=false with '
                 'format_encoder_unavailable/format_not_supported, requested_formats, '
                 'supported_formats, recommended_formats, actual_format, and '
                 'downgrade_allowed=false.<br>artifacts (list)<br>error (dict|null)<br>meta '
                 '(dict)<br>projections (dict, 可选)',
  'param_names': ['session_id',
                  'texture_id',
                  'subresource',
                  'output_path',
                  'file_format',
                  'channels',
                  'remap',
                  'flip_y'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'export',
  'input_schema': {'type': 'object',
                   'properties': {'event_id': {'type': 'integer',
                                               'minimum': 0,
                                               'description': 'Replay event; omitted uses the '
                                                              'owning session current event.'},
                                  'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'texture_id': {'description': 'texture_id (str)',
                                                 'type': 'string'},
                                  'subresource': {'type': 'object',
                                                  'properties': {'mip': {'type': 'integer',
                                                                         'minimum': 0},
                                                                 'slice': {'type': 'integer',
                                                                           'minimum': 0},
                                                                 'sample': {'type': 'integer',
                                                                            'minimum': 0}},
                                                  'additionalProperties': False},
                                  'output_path': {'description': 'output_path (str)',
                                                  'type': 'string'},
                                  'file_format': {'description': "file_format (str, 可选, 默认 'png'): "
                                                                 'canonical output format; high '
                                                                 'precision formats such as '
                                                                 "'hdr'/'exr' fail closed if "
                                                                 'unavailable',
                                                  'type': 'string'},
                                  'channels': {'description': "channels (str, 可选, 默认 'rgba')",
                                               'type': 'string'},
                                  'remap': {'description': 'remap (dict, 可选): {black_point, '
                                                           'white_point, gamma, hdr_clamp?}',
                                            'type': 'object'},
                                  'flip_y': {'description': 'flip_y (bool, 可选, 默认 false)',
                                             'type': 'boolean'}},
                   'required': ['session_id', 'texture_id', 'output_path'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position', 'artifact_write'],
  'evidence_kind': 'measurement',
  'path_inputs': [{'name': 'output_path', 'access': 'write'}]},
 {'name': 'rd.macro.find_state_change_point',
  'group': '3.15，专家级宏工作流 (Expert Macro Workflows)',
  'description': '在 event 区间内搜索“某个状态何时从 A 变为 B”（通过 pipeline diff 快速二分/线性扫描）。',
  'parameter_raw': 'session_id (string): session_id (str)<br>event_range (object): See '
                   'input_schema for constraints.<br>state_path (string): Dot-separated path into '
                   'rd.pipeline.get_state pipeline_state, including numeric array '
                   'indices.<br>target_value (any): target_value (any): 期望值<br>max_events '
                   '(integer, optional): See input_schema for constraints.',
  'returns_raw': 'data: {found_event_id: integer|null, examined_events: integer, complete: '
                 'boolean, range_exhausted: boolean, budget_exhausted: boolean}. Visits real event '
                 'IDs only; cancellation interrupts between events.',
  'param_names': ['session_id', 'event_range', 'state_path', 'target_value', 'max_events'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'macro',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'event_range': {'type': 'object',
                                                  'properties': {'start_event_id': {'type': 'integer',
                                                                                    'minimum': 0},
                                                                 'end_event_id': {'type': 'integer',
                                                                                  'minimum': 0}},
                                                  'required': ['start_event_id', 'end_event_id'],
                                                  'additionalProperties': False},
                                  'state_path': {'description': 'Dot-separated path into '
                                                                'rd.pipeline.get_state '
                                                                'pipeline_state, including numeric '
                                                                'array indices.',
                                                 'type': 'string'},
                                  'target_value': {'description': 'target_value (any): 期望值'},
                                  'max_events': {'type': 'integer', 'minimum': 1, 'default': 2000}},
                   'required': ['session_id', 'event_range', 'state_path', 'target_value'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.mesh.decode_index_data',
  'group': '3.7，缓冲区与网格数据访问 (Buffer & Mesh Data Access)',
  'description': '解码 Index Buffer（16/32-bit）为 index 列表。',
  'parameter_raw': 'session_id (string): session_id (str)<br>index_buffer_id (string): '
                   'index_buffer_id (str)<br>format (string): format (str): '
                   "'R16_UINT'|'R32_UINT'<br>index_offset (integer, optional): index_offset (int, "
                   '可选, 默认 0)<br>index_count (integer, optional): index_count (int, 可选, 默认 '
                   '256)<br>base_vertex (integer, optional): base_vertex (int, 可选, 默认 0)',
  'returns_raw': 'ok (bool)<br>data (dict): {indices}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id',
                  'index_buffer_id',
                  'format',
                  'index_offset',
                  'index_count',
                  'base_vertex'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'mesh',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'index_buffer_id': {'description': 'index_buffer_id (str)',
                                                      'type': 'string'},
                                  'format': {'description': "format (str): 'R16_UINT'|'R32_UINT'",
                                             'type': 'string',
                                             'enum': ['u16', 'u32']},
                                  'index_offset': {'description': 'index_offset (int, 可选, 默认 0)',
                                                   'type': 'integer'},
                                  'index_count': {'description': 'index_count (int, 可选, 默认 256)',
                                                  'type': 'integer'},
                                  'base_vertex': {'description': 'base_vertex (int, 可选, 默认 0)',
                                                  'type': 'integer'}},
                   'required': ['session_id', 'index_buffer_id', 'format'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.mesh.get_drawcall_mesh_config',
  'group': '3.7，缓冲区与网格数据访问 (Buffer & Mesh Data Access)',
  'description': '获取当前 drawcall 的 mesh 配置：使用哪些 VB/IB、topology、baseVertex、indexOffset、instanceCount '
                 '等。',
  'parameter_raw': 'session_id (string): session_id (str)<br>event_id (integer, optional): '
                   'event_id (int, 可选); instance (integer, default 0); max_vertices (integer, default 128; 0 reads full draw)',
  'returns_raw': 'ok (bool)<br>data (dict): {mesh_config: {event_id, topology, bindings, vertex_input}}; vertex_input includes source=vs_input, vertex_rows with draw/vertex indices and typed semantic values, attributes position/normal/uv status, layout, index_binding, truncated. Values are shader inputs in original coordinate space; packed normal encoding is not interpreted as a geometric normal<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'event_id', 'instance', 'max_vertices'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'mesh',
  'input_schema': {'type': 'object',
                   'properties': {'instance': {'type': 'integer', 'minimum': 0, 'default': 0}, 'max_vertices': {'type': 'integer', 'minimum': 0, 'default': 128}, 'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'event_id': {'description': 'event_id (int, 可选); instance (integer, default 0); max_vertices (integer, default 128; 0 reads full draw)',
                                               'type': 'integer',
                                               'minimum': 0}},
                   'required': ['session_id'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.mesh.get_post_transform_data',
  'group': '3.7，缓冲区与网格数据访问 (Buffer & Mesh Data Access)',
  'description': 'Read post-transform vertex data from VS or GS at a replay event. view_index '
                 'selects an integer multiview/VR view; unbound GS is reported explicitly.',
  'parameter_raw': 'session_id (string): session_id (str)<br>event_id (integer, optional): '
                   'event_id (int, 可选): 缺省使用当前 active event<br>instance (integer, optional): '
                   'instance (int, 可选, 默认 0)<br>view_index (integer, optional): Integer '
                   'multiview/VR view index.<br>max_vertices (integer, optional): max_vertices '
                   '(int, 可选): 限制导出顶点数<br>stage (string): See input_schema for constraints.',
  'returns_raw': 'vertex_rows retain raw bytes and nullable typed position. attributes explicitly reports position/normal/uv present or unsupported; outputs separately exposes a verified D3D11/12 stream-zero float output signature layout and per-row outputs, without assigning TEXCOORD to normal. source=post_transform; no input values are substituted. No attribute layout is guessed. truncated is null when an unbounded native buffer view prevents proving total size.<br>ok (bool)<br>data (dict): {mesh_data}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'event_id', 'instance', 'view_index', 'max_vertices', 'stage'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'mesh',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'event_id': {'description': 'event_id (int, 可选): 缺省使用当前 active '
                                                              'event',
                                               'type': 'integer',
                                               'minimum': 0},
                                  'instance': {'description': 'instance (int, 可选, 默认 0)',
                                               'type': 'integer',
                                               'minimum': 0},
                                  'view_index': {'type': 'integer',
                                                 'minimum': 0,
                                                 'default': 0,
                                                 'description': 'Integer multiview/VR view index.'},
                                  'max_vertices': {'description': 'max_vertices (int, 可选): 限制导出顶点数',
                                                   'type': 'integer',
                                                   'minimum': 0},
                                  'stage': {'type': 'string', 'enum': ['vs', 'gs']}},
                   'required': ['session_id', 'stage'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.perf.describe_counter',
  'group': '3.10，性能与高级分析 (Performance & Advanced Analysis)',
  'description': '获取单个 counter 的详细描述。',
  'parameter_raw': 'session_id (string): session_id (str)<br>counter_id (integer): counter_id '
                   '(int)',
  'returns_raw': 'ok (bool)<br>data (dict): {counter}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'counter_id'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'perf',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'counter_id': {'description': 'counter_id (int)',
                                                 'type': 'integer'}},
                   'required': ['session_id', 'counter_id'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': [],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.perf.enumerate_counters',
  'group': '3.10，性能与高级分析 (Performance & Advanced Analysis)',
  'description': '枚举可用的 GPU counters。',
  'parameter_raw': 'session_id (string): session_id (str)',
  'returns_raw': 'ok (bool)<br>data (dict): {counters}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'perf',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'}},
                   'required': ['session_id'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': [],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.perf.get_event_durations',
  'group': '3.10，性能与高级分析 (Performance & Advanced Analysis)',
  'description': '获取每个 event 的 GPU duration（若支持 timing queries；可用于定位慢 draw）。',
  'parameter_raw': 'session_id (string): session_id (str)<br>event_range (object, optional): See '
                   'input_schema for constraints.<br>max_events (integer, optional): max_events '
                   '(int, 可选, 默认 20000)',
  'returns_raw': 'ok (bool)<br>data (dict): {durations}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'event_range', 'max_events'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'perf',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'event_range': {'type': 'object',
                                                  'properties': {'start_event_id': {'type': 'integer',
                                                                                    'minimum': 0},
                                                                 'end_event_id': {'type': 'integer',
                                                                                  'minimum': 0}},
                                                  'required': ['start_event_id', 'end_event_id'],
                                                  'additionalProperties': False},
                                  'max_events': {'description': 'max_events (int, 可选, 默认 20000)',
                                                 'type': 'integer'}},
                   'required': ['session_id'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': 'measurement',
  'path_inputs': []},
 {'name': 'rd.perf.sample_counters',
  'group': '3.10，性能与高级分析 (Performance & Advanced Analysis)',
  'description': '对当前帧/指定 event 范围采样 counters（可能较慢）。',
  'parameter_raw': 'session_id (string): session_id (str)<br>counter_ids (array): counter_ids '
                   '(list[int])<br>event_range (object, optional): See input_schema for '
                   'constraints.<br>stride (integer, optional): stride (int, 可选, 默认 1): 每隔多少个 '
                   'event 采样一次（降低成本）',
  'returns_raw': 'ok (bool)<br>data (dict): {samples}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'counter_ids', 'event_range', 'stride'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'perf',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'counter_ids': {'description': 'counter_ids (list[int])',
                                                  'type': 'array',
                                                  'items': {}},
                                  'event_range': {'type': 'object',
                                                  'properties': {'start_event_id': {'type': 'integer',
                                                                                    'minimum': 0},
                                                                 'end_event_id': {'type': 'integer',
                                                                                  'minimum': 0}},
                                                  'required': ['start_event_id', 'end_event_id'],
                                                  'additionalProperties': False},
                                  'stride': {'description': 'stride (int, 可选, 默认 1): 每隔多少个 event '
                                                            '采样一次（降低成本）',
                                             'type': 'integer'}},
                   'required': ['session_id', 'counter_ids'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': 'measurement',
  'path_inputs': []},
 {'name': 'rd.pipeline.get_constant_buffers',
  'group': '3.4，管线状态查询 (Pipeline State Inspection)',
  'description': '获取指定 stage 的 Constant Buffer 绑定（slot/buffer/offset/size）。',
  'parameter_raw': 'session_id (string): session_id (str)<br>stage (string): stage '
                   '(str)<br>include_contents (boolean, optional): include_contents (bool, 可选, 默认 '
                   'false): 若 true 则额外解码变量值（可能较慢）<br>max_bytes (integer, optional): max_bytes '
                   '(int, 可选, 默认 1048576): 解码上限，避免超大 CB 导致内存压力<br>event_id (integer, optional): '
                   'Replay event; omitted uses the owning session current event.<br>array_index '
                   '(integer, optional): See input_schema for constraints.<br>flatten (boolean, '
                   'optional): See input_schema for constraints.<br>slot (integer, optional): See '
                   'input_schema for constraints.',
  'returns_raw': 'ok (bool)<br>data (dict): {constant_buffers}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id',
                  'stage',
                  'include_contents',
                  'max_bytes',
                  'event_id',
                  'array_index',
                  'flatten',
                  'slot'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'pipeline',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'stage': {'description': 'stage (str)', 'type': 'string'},
                                  'include_contents': {'description': 'include_contents (bool, 可选, '
                                                                      '默认 false): 若 true '
                                                                      '则额外解码变量值（可能较慢）',
                                                       'type': 'boolean'},
                                  'max_bytes': {'description': 'max_bytes (int, 可选, 默认 1048576): '
                                                               '解码上限，避免超大 CB 导致内存压力',
                                                'type': 'integer'},
                                  'event_id': {'type': 'integer',
                                               'minimum': 0,
                                               'description': 'Replay event; omitted uses the '
                                                              'owning session current event.'},
                                  'array_index': {'type': 'integer', 'minimum': 0},
                                  'flatten': {'type': 'boolean'},
                                  'slot': {'type': 'integer', 'minimum': 0}},
                   'required': ['session_id', 'stage'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.pipeline.get_index_buffer',
  'group': '3.4，管线状态查询 (Pipeline State Inspection)',
  'description': '获取当前绑定的 Index Buffer（resource_id/format/offset）。',
  'parameter_raw': 'session_id (string): session_id (str)<br>event_id (integer, optional): Replay '
                   'event; omitted uses the owning session current event.',
  'returns_raw': 'ok (bool)<br>data (dict): {index_buffer}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'event_id'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'pipeline',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'event_id': {'type': 'integer',
                                               'minimum': 0,
                                               'description': 'Replay event; omitted uses the '
                                                              'owning session current event.'}},
                   'required': ['session_id'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.pipeline.get_resource_bindings',
  'group': '3.4，管线状态查询 (Pipeline State Inspection)',
  'description': '获取指定 stage 的资源绑定（SRV/CBV/RO-Images 等）。',
  'parameter_raw': 'session_id (string): session_id (str)<br>stage (string): stage (str): '
                   "'VS'|'HS'|'DS'|'GS'|'PS'|'CS'|'AS'|'MS'|'RT'<br>type (string, optional): See "
                   'input_schema for constraints.<br>event_id (integer, optional): Replay event; '
                   'omitted uses the owning session current event.',
  'returns_raw': 'ok (bool)<br>data (dict): {bindings}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'stage', 'type', 'event_id'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'pipeline',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'stage': {'description': 'stage (str): '
                                                           "'VS'|'HS'|'DS'|'GS'|'PS'|'CS'|'AS'|'MS'|'RT'",
                                            'type': 'string'},
                                  'type': {'type': 'string',
                                           'enum': ['SRV', 'UAV', 'CBV', 'Sampler']},
                                  'event_id': {'type': 'integer',
                                               'minimum': 0,
                                               'description': 'Replay event; omitted uses the '
                                                              'owning session current event.'}},
                   'required': ['session_id', 'stage'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.pipeline.get_shader',
  'group': '3.4，管线状态查询 (Pipeline State Inspection)',
  'description': '获取指定 stage 的 shader 句柄与摘要信息（resource_id、entry、debug info 可用性等）。',
  'parameter_raw': 'session_id (string): session_id (str)<br>stage (string): stage '
                   '(str)<br>event_id (integer, optional): Replay event; omitted uses the owning '
                   'session current event.',
  'returns_raw': 'ok (bool)<br>data (dict): {shader}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'stage', 'event_id'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'pipeline',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'stage': {'description': 'stage (str)', 'type': 'string'},
                                  'event_id': {'type': 'integer',
                                               'minimum': 0,
                                               'description': 'Replay event; omitted uses the '
                                                              'owning session current event.'}},
                   'required': ['session_id', 'stage'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.pipeline.get_stage_state',
  'group': '3.4，管线状态查询 (Pipeline State Inspection)',
  'description': '获取指定 Shader Stage 的 Pipeline 子状态。',
  'parameter_raw': 'session_id (string): session_id (str)<br>stage (string): stage (str): '
                   "'VS'|'HS'|'DS'|'GS'|'PS'|'CS'|'AS'|'MS'|'RT'<br>event_id (integer, optional): "
                   'Replay event; omitted uses the owning session current event.<br>max_bytes '
                   '(integer, optional): See input_schema for constraints.',
  'returns_raw': 'ok (bool)<br>data (dict): {stage_state}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'stage', 'event_id', 'max_bytes'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'pipeline',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'stage': {'description': 'stage (str): '
                                                           "'VS'|'HS'|'DS'|'GS'|'PS'|'CS'|'AS'|'MS'|'RT'",
                                            'type': 'string'},
                                  'event_id': {'type': 'integer',
                                               'minimum': 0,
                                               'description': 'Replay event; omitted uses the '
                                                              'owning session current event.'},
                                  'max_bytes': {'type': 'integer', 'minimum': 0}},
                   'required': ['session_id', 'stage'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.pipeline.get_state',
  'group': '3.4，管线状态查询 (Pipeline State Inspection)',
  'description': '获取当前 active event 的完整 Pipeline State（返回结构按 API 类型组织）。',
  'parameter_raw': 'session_id (string): session_id (str)<br>event_id (integer): event_id (int, '
                   '可选): 缺省为当前 active event，并回传 resolved_event_id<br>context_id (string): '
                   'context_id (str, optional): choose the context to use; defaults to the current '
                   'daemon context<br>detail (string): detail<br>sections (array): Only request '
                   'these state sections; omitted selects all.',
  'returns_raw': 'Shader hash is SHA-256 of recorded shader rawBytes, or null when unavailable; debug_name is the native non-autogenerated shader resource debug name or null; resource_name retains the native display name including autogenerated names; debug_source_files lists actual debug source filenames separately. Neither is derived from ResourceId.<br>data: resolved_event_id, pipeline_state. Full indexed viewports/scissors, blend '
                 'options and complete front/back stencil. API-specific sections carry api, status '
                 'and native data; failed reads are not empty states.',
  'param_names': ['session_id', 'event_id', 'context_id', 'detail', 'sections'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'pipeline',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'event_id': {'description': 'event_id (int, 可选): 缺省为当前 active '
                                                              'event，并回传 resolved_event_id',
                                               'type': 'integer',
                                               'minimum': 0},
                                  'context_id': {'description': 'context_id (str, optional): '
                                                                'choose the context to use; '
                                                                'defaults to the current daemon '
                                                                'context',
                                                 'type': 'string'},
                                  'detail': {'type': 'string',
                                             'enum': ['summary', 'full'],
                                             'default': 'full'},
                                  'sections': {'type': 'array',
                                               'items': {'type': 'string',
                                                         'enum': ['shaders',
                                                                  'output_targets',
                                                                  'topology',
                                                                  'viewports_scissors',
                                                                  'blend',
                                                                  'depth_stencil',
                                                                  'bindings',
                                                                  'vertex_input',
                                                                  'rasterizer',
                                                                  'multisample',
                                                                  'push_constants',
                                                                  'dynamic_state',
                                                                  'root_signature',
                                                                  'descriptor_heaps',
                                                                  'resource_states']},
                                               'description': 'Only request these state sections; '
                                                              'omitted selects all.'}},
                   'required': ['session_id'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.pipeline.get_vertex_buffers',
  'group': '3.4，管线状态查询 (Pipeline State Inspection)',
  'description': '获取当前绑定的 Vertex Buffers 列表（含 slot/stride/offset/resource_id）。',
  'parameter_raw': 'session_id (string): session_id (str)<br>event_id (integer, optional): Replay '
                   'event; omitted uses the owning session current event.',
  'returns_raw': 'ok (bool)<br>data (dict): {vertex_buffers}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'event_id'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'pipeline',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'event_id': {'type': 'integer',
                                               'minimum': 0,
                                               'description': 'Replay event; omitted uses the '
                                                              'owning session current event.'}},
                   'required': ['session_id'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.remote.connect',
  'group': '3.12，远程连接与自动化抓帧 (Remote Capture & Target Control)',
  'description': '连接到远程 RenderDoc server；支持 direct RenderDoc endpoint 和 Android adb bootstrap。',
  'parameter_raw': 'host (string, optional): host (str, renderdoc transport required; adb_android '
                   'optional)<br>port (integer, optional): port (int, optional, default '
                   '38920)<br>timeout_ms (integer, optional): timeout_ms (int, optional, default '
                   '5000)<br>options (object, optional): options (dict, optional): {transport?: '
                   "'renderdoc'|'adb_android', device_serial?, local_port?, install_apk?, "
                   'push_config?}',
  'returns_raw': 'ok (bool)<br>data (dict): {remote_id, server_info}; for adb_android, '
                 'server_info/bootstrap details identify the endpoint, device and ownership: '
                 'started_activity/owned_pids describe only this attempt; existing helpers are '
                 'borrowed without install, configuration or launch. Success requires RenderDoc '
                 'connection and Ping. Socket readiness waits at most 15 seconds within the total '
                 'timeout; query failure, missing/ambiguous socket and native busy/incompatible '
                 'status remain distinct. Disconnect closes only this connection and verified '
                 'owned resources. Cleanup failures accompany the original error.<br>artifacts '
                 '(list)<br>error (dict|null): direct renderdoc transport requires host; '
                 'adb_android may omit host and defaults to the local bootstrap endpoint; '
                 'unsupported transports return `remote_transport_unsupported`<br>meta '
                 '(dict)<br>projections (dict, optional)',
  'param_names': ['host', 'port', 'timeout_ms', 'options'],
  'prerequisites': [{'requires': 'capability.remote',
                     'via_tools': ['rd.core.init'],
                     'reason': 'Remote tools require remote capability to be enabled for the '
                               'current runtime.'}],
  'namespace': 'remote',
  'input_schema': {'type': 'object',
                   'properties': {'host': {'description': 'host (str, renderdoc transport '
                                                          'required; adb_android optional)',
                                           'type': 'string'},
                                  'port': {'description': 'port (int, optional, default 38920)',
                                           'type': 'integer'},
                                  'timeout_ms': {'description': 'timeout_ms (int, optional, '
                                                                'default 5000)',
                                                 'type': 'integer'},
                                  'options': {'description': 'options (dict, optional): '
                                                             '{transport?: '
                                                             "'renderdoc'|'adb_android', "
                                                             'device_serial?, local_port?, '
                                                             'install_apk?, push_config?}',
                                              'type': 'object'}},
                   'required': [],
                   'additionalProperties': False},
  'scope': 'global',
  'effects': ['remote_control'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.remote.copy_capture',
  'group': '3.12，远程连接与自动化抓帧 (Remote Capture & Target Control)',
  'description': '将远程 capture 拷贝到本地路径（也可用于下载）。',
  'parameter_raw': 'remote_id (string): remote_id (str)<br>capture_id (integer): capture_id '
                   '(int)<br>local_path (string): local_path (str)',
  'returns_raw': 'ok (bool)<br>data (dict): {saved_path}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['remote_id', 'capture_id', 'local_path'],
  'prerequisites': [{'requires': 'remote_id',
                     'via_tools': ['rd.remote.connect'],
                     'reason': 'This tool targets a live remote endpoint handle.'},
                    {'requires': 'capability.remote',
                     'via_tools': ['rd.core.init'],
                     'reason': 'Remote tools require remote capability to be enabled for the '
                               'current runtime.'}],
  'namespace': 'remote',
  'input_schema': {'type': 'object',
                   'properties': {'remote_id': {'description': 'remote_id (str)', 'type': 'string'},
                                  'capture_id': {'description': 'capture_id (int)',
                                                 'type': 'integer'},
                                  'local_path': {'description': 'local_path (str)',
                                                 'type': 'string'}},
                   'required': ['remote_id', 'capture_id', 'local_path'],
                   'additionalProperties': False},
  'scope': 'global',
  'effects': ['remote_control'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.remote.delete_capture',
  'group': '3.12，远程连接与自动化抓帧 (Remote Capture & Target Control)',
  'description': '删除远程服务器上的 capture（谨慎使用）。',
  'parameter_raw': 'remote_id (string): remote_id (str)<br>capture_id (integer): capture_id (int)',
  'returns_raw': 'ok (bool)<br>data (dict): tool-specific payload<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['remote_id', 'capture_id'],
  'prerequisites': [{'requires': 'remote_id',
                     'via_tools': ['rd.remote.connect'],
                     'reason': 'This tool targets a live remote endpoint handle.'},
                    {'requires': 'capability.remote',
                     'via_tools': ['rd.core.init'],
                     'reason': 'Remote tools require remote capability to be enabled for the '
                               'current runtime.'}],
  'namespace': 'remote',
  'input_schema': {'type': 'object',
                   'properties': {'remote_id': {'description': 'remote_id (str)', 'type': 'string'},
                                  'capture_id': {'description': 'capture_id (int)',
                                                 'type': 'integer'}},
                   'required': ['remote_id', 'capture_id'],
                   'additionalProperties': False},
  'scope': 'global',
  'effects': ['remote_control'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.remote.disconnect',
  'group': '3.12，远程连接与自动化抓帧 (Remote Capture & Target Control)',
  'description': '断开远程连接。',
  'parameter_raw': 'remote_id (string): remote_id (str)',
  'returns_raw': 'ok (bool)<br>data (dict): tool-specific payload<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['remote_id'],
  'prerequisites': [{'requires': 'remote_id',
                     'via_tools': ['rd.remote.connect'],
                     'reason': 'This tool targets a live remote endpoint handle.'},
                    {'requires': 'capability.remote',
                     'via_tools': ['rd.core.init'],
                     'reason': 'Remote tools require remote capability to be enabled for the '
                               'current runtime.'}],
  'namespace': 'remote',
  'input_schema': {'type': 'object',
                   'properties': {'remote_id': {'description': 'remote_id (str)',
                                                'type': 'string'}},
                   'required': ['remote_id'],
                   'additionalProperties': False},
  'scope': 'global',
  'effects': ['remote_control'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.remote.launch_app',
  'group': '3.12，远程连接与自动化抓帧 (Remote Capture & Target Control)',
  'description': '在远程机器启动应用并注入 RenderDoc（若 server 支持）。',
  'parameter_raw': 'remote_id (string): remote_id (str)<br>exe_path (string): exe_path '
                   '(str)<br>working_dir (string, optional): working_dir (str, 可选)<br>cmdline '
                   '(string, optional): cmdline (str, 可选)<br>env (object, optional): env (dict, '
                   '可选)<br>capture_options (object, optional): capture_options (dict, 可选): 参考 '
                   'rd.remote.set_capture_options',
  'returns_raw': 'ok (bool)<br>data (dict): {target_id, pid}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['remote_id', 'exe_path', 'working_dir', 'cmdline', 'env', 'capture_options'],
  'prerequisites': [{'requires': 'remote_id',
                     'via_tools': ['rd.remote.connect'],
                     'reason': 'This tool targets a live remote endpoint handle.'},
                    {'requires': 'capability.remote',
                     'via_tools': ['rd.core.init'],
                     'reason': 'Remote tools require remote capability to be enabled for the '
                               'current runtime.'}],
  'namespace': 'remote',
  'input_schema': {'type': 'object',
                   'properties': {'remote_id': {'description': 'remote_id (str)', 'type': 'string'},
                                  'exe_path': {'description': 'exe_path (str)', 'type': 'string'},
                                  'working_dir': {'description': 'working_dir (str, 可选)',
                                                  'type': 'string'},
                                  'cmdline': {'description': 'cmdline (str, 可选)', 'type': 'string'},
                                  'env': {'description': 'env (dict, 可选)', 'type': 'object'},
                                  'capture_options': {'description': 'capture_options (dict, 可选): '
                                                                     '参考 '
                                                                     'rd.remote.set_capture_options',
                                                      'type': 'object'}},
                   'required': ['remote_id', 'exe_path'],
                   'additionalProperties': False},
  'scope': 'global',
  'effects': ['remote_control'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.remote.list_captures',
  'group': '3.12，远程连接与自动化抓帧 (Remote Capture & Target Control)',
  'description': '列出远程服务器上所有可用捕获。',
  'parameter_raw': 'remote_id (string): remote_id (str)',
  'returns_raw': 'ok (bool)<br>data (dict): {captures}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['remote_id'],
  'prerequisites': [{'requires': 'remote_id',
                     'via_tools': ['rd.remote.connect'],
                     'reason': 'This tool targets a live remote endpoint handle.'},
                    {'requires': 'capability.remote',
                     'via_tools': ['rd.core.init'],
                     'reason': 'Remote tools require remote capability to be enabled for the '
                               'current runtime.'}],
  'namespace': 'remote',
  'input_schema': {'type': 'object',
                   'properties': {'remote_id': {'description': 'remote_id (str)',
                                                'type': 'string'}},
                   'required': ['remote_id'],
                   'additionalProperties': False},
  'scope': 'global',
  'effects': ['remote_control'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.remote.list_targets',
  'group': '3.12，远程连接与自动化抓帧 (Remote Capture & Target Control)',
  'description': '列出远程可连接的 targets（已注入/已运行应用、可抓帧进程等）。',
  'parameter_raw': 'remote_id (string): remote_id (str)',
  'returns_raw': 'ok (bool)<br>data (dict): {targets}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['remote_id'],
  'prerequisites': [{'requires': 'remote_id',
                     'via_tools': ['rd.remote.connect'],
                     'reason': 'This tool targets a live remote endpoint handle.'},
                    {'requires': 'capability.remote',
                     'via_tools': ['rd.core.init'],
                     'reason': 'Remote tools require remote capability to be enabled for the '
                               'current runtime.'}],
  'namespace': 'remote',
  'input_schema': {'type': 'object',
                   'properties': {'remote_id': {'description': 'remote_id (str)',
                                                'type': 'string'}},
                   'required': ['remote_id'],
                   'additionalProperties': False},
  'scope': 'global',
  'effects': ['remote_control'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.remote.ping',
  'group': '3.12，远程连接与自动化抓帧 (Remote Capture & Target Control)',
  'description': '检查远程连接可用性与延迟。',
  'parameter_raw': 'remote_id (string): remote_id (str)',
  'returns_raw': 'ok (bool)<br>data (dict): {latency_ms}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['remote_id'],
  'prerequisites': [{'requires': 'remote_id',
                     'via_tools': ['rd.remote.connect'],
                     'reason': 'This tool targets a live remote endpoint handle.'},
                    {'requires': 'capability.remote',
                     'via_tools': ['rd.core.init'],
                     'reason': 'Remote tools require remote capability to be enabled for the '
                               'current runtime.'}],
  'namespace': 'remote',
  'input_schema': {'type': 'object',
                   'properties': {'remote_id': {'description': 'remote_id (str)',
                                                'type': 'string'}},
                   'required': ['remote_id'],
                   'additionalProperties': False},
  'scope': 'global',
  'effects': ['remote_control'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.remote.queue_capture',
  'group': '3.12，远程连接与自动化抓帧 (Remote Capture & Target Control)',
  'description': '在远程 target 上排队捕获（例如下一次 Present/下一帧），并返回队列状态。',
  'parameter_raw': 'remote_id (string): remote_id (str)<br>target_id (string, optional): target_id '
                   '(str, 可选)<br>num_frames (integer, optional): num_frames (int, 可选, 默认 1)',
  'returns_raw': 'ok (bool)<br>data (dict): {queue_status}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['remote_id', 'target_id', 'num_frames'],
  'prerequisites': [{'requires': 'remote_id',
                     'via_tools': ['rd.remote.connect'],
                     'reason': 'This tool targets a live remote endpoint handle.'},
                    {'requires': 'capability.remote',
                     'via_tools': ['rd.core.init'],
                     'reason': 'Remote tools require remote capability to be enabled for the '
                               'current runtime.'}],
  'namespace': 'remote',
  'input_schema': {'type': 'object',
                   'properties': {'remote_id': {'description': 'remote_id (str)', 'type': 'string'},
                                  'target_id': {'description': 'target_id (str, 可选)',
                                                'type': 'string'},
                                  'num_frames': {'description': 'num_frames (int, 可选, 默认 1)',
                                                 'type': 'integer'}},
                   'required': ['remote_id'],
                   'additionalProperties': False},
  'scope': 'global',
  'effects': ['remote_control'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.remote.set_capture_options',
  'group': '3.12，远程连接与自动化抓帧 (Remote Capture & Target Control)',
  'description': '设置远程抓帧参数（保存路径、frame limit、禁止/允许某些 API 特性等）。',
  'parameter_raw': 'remote_id (string): remote_id (str)<br>options (object): options (dict): '
                   '{capture_file_path_template?, capture_all_cmd_lists?, allow_vsync?, '
                   'hook_into_children?, ref_all_resources?, ...}',
  'returns_raw': 'ok (bool)<br>data (dict): {applied}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['remote_id', 'options'],
  'prerequisites': [{'requires': 'remote_id',
                     'via_tools': ['rd.remote.connect'],
                     'reason': 'This tool targets a live remote endpoint handle.'},
                    {'requires': 'capability.remote',
                     'via_tools': ['rd.core.init'],
                     'reason': 'Remote tools require remote capability to be enabled for the '
                               'current runtime.'}],
  'namespace': 'remote',
  'input_schema': {'type': 'object',
                   'properties': {'remote_id': {'description': 'remote_id (str)', 'type': 'string'},
                                  'options': {'description': 'options (dict): '
                                                             '{capture_file_path_template?, '
                                                             'capture_all_cmd_lists?, '
                                                             'allow_vsync?, hook_into_children?, '
                                                             'ref_all_resources?, ...}',
                                              'type': 'object'}},
                   'required': ['remote_id', 'options'],
                   'additionalProperties': False},
  'scope': 'global',
  'effects': ['remote_control'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.remote.trigger_capture',
  'group': '3.12，远程连接与自动化抓帧 (Remote Capture & Target Control)',
  'description': '在远程 target 上触发一次或多次捕获。',
  'parameter_raw': 'remote_id (string): remote_id (str)<br>target_id (string, optional): target_id '
                   '(str, 可选): 缺省表示 server 默认 target（若存在）<br>num_frames (integer, optional): '
                   'num_frames (int, 可选, 默认 1)<br>capture_delay_ms (integer, optional): '
                   'capture_delay_ms (int, 可选, 默认 0): 延迟触发',
  'returns_raw': 'ok (bool)<br>data (dict): {captures}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['remote_id', 'target_id', 'num_frames', 'capture_delay_ms'],
  'prerequisites': [{'requires': 'remote_id',
                     'via_tools': ['rd.remote.connect'],
                     'reason': 'This tool targets a live remote endpoint handle.'},
                    {'requires': 'capability.remote',
                     'via_tools': ['rd.core.init'],
                     'reason': 'Remote tools require remote capability to be enabled for the '
                               'current runtime.'}],
  'namespace': 'remote',
  'input_schema': {'type': 'object',
                   'properties': {'remote_id': {'description': 'remote_id (str)', 'type': 'string'},
                                  'target_id': {'description': 'target_id (str, 可选): 缺省表示 server '
                                                               '默认 target（若存在）',
                                                'type': 'string'},
                                  'num_frames': {'description': 'num_frames (int, 可选, 默认 1)',
                                                 'type': 'integer'},
                                  'capture_delay_ms': {'description': 'capture_delay_ms (int, 可选, '
                                                                      '默认 0): 延迟触发',
                                                       'type': 'integer'}},
                   'required': ['remote_id'],
                   'additionalProperties': False},
  'scope': 'global',
  'effects': ['remote_control'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.replay.get_api_properties',
  'group': '3.2，捕获文件与 Replay Session (Capture & Replay)',
  'description': '获取 Replay Session 的 API 属性（如 shader debug 支持、counter 支持等）。',
  'parameter_raw': 'session_id (string): session_id (str)',
  'returns_raw': 'ok (bool)<br>data (dict): {api_properties}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'replay',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'}},
                   'required': ['session_id'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.replay.get_driver_info',
  'group': '3.2，捕获文件与 Replay Session (Capture & Replay)',
  'description': '获取回放 driver 信息（版本、vendor、device、driver 字符串等）。',
  'parameter_raw': 'session_id (string): session_id (str)',
  'returns_raw': 'ok (bool)<br>data (dict): {driver_info}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'replay',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'}},
                   'required': ['session_id'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.replay.get_frame_info',
  'group': '3.2，捕获文件与 Replay Session (Capture & Replay)',
  'description': '获取当前/指定帧的统计信息（drawcall 数、marker 数、时长等）。',
  'parameter_raw': 'session_id (string): session_id (str)<br>frame_index (integer, optional): '
                   'frame_index (int, 可选): 缺省为当前帧',
  'returns_raw': 'ok (bool)<br>data (dict): {frame_info}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'frame_index'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'replay',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'frame_index': {'description': 'frame_index (int, 可选): 缺省为当前帧',
                                                  'type': 'integer'}},
                   'required': ['session_id'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.replay.set_frame',
  'group': '3.2，捕获文件与 Replay Session (Capture & Replay)',
  'description': '切换当前回放帧（会重置 active event 到该帧起始）。',
  'parameter_raw': 'session_id (string): session_id (str)<br>frame_index (integer): frame_index '
                   '(int)',
  'returns_raw': 'ok (bool)<br>data (dict): {active_event_id}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'frame_index'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'replay',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'frame_index': {'description': 'frame_index (int)',
                                                  'type': 'integer'}},
                   'required': ['session_id', 'frame_index'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.resource.estimate_memory',
  'group': '3.5，资源探查 (Resource Inspection & History)',
  'description': '估算资源占用内存，按格式/维度推算，用于快速筛选大资源。',
  'parameter_raw': 'session_id (string): session_id (str)<br>resource_id (string): resource_id '
                   '(str)',
  'returns_raw': 'ok (bool)<br>data (dict): {estimated_bytes, breakdown}<br>artifacts '
                 '(list)<br>error (dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'resource_id'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'resource',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'resource_id': {'description': 'resource_id (str)',
                                                  'type': 'string'}},
                   'required': ['session_id', 'resource_id'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.resource.get_details',
  'group': '3.5，资源探查 (Resource Inspection & History)',
  'description': '获取资源详细信息，兼容 V3；根据资源类型返回不同字段。',
  'parameter_raw': 'session_id (string): session_id (str)<br>resource_id (string): resource_id '
                   '(str)<br>include_initialization (boolean): Recorded initialization chunks and '
                   'parent/derived resources; not a creation call-stack claim.',
  'returns_raw': 'ok (bool)<br>data (dict): {details}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'resource_id', 'include_initialization'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'resource',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'resource_id': {'description': 'resource_id (str)',
                                                  'type': 'string'},
                                  'include_initialization': {'type': 'boolean',
                                                             'default': False,
                                                             'description': 'Recorded '
                                                                            'initialization chunks '
                                                                            'and parent/derived '
                                                                            'resources; not a '
                                                                            'creation call-stack '
                                                                            'claim.'}},
                   'required': ['session_id', 'resource_id'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.resource.get_usage',
  'group': '3.5，资源探查 (Resource Inspection & History)',
  'description': '获取资源的使用情况，即哪些 event 读/写/绑定该资源。',
  'parameter_raw': 'session_id (string): session_id (str)<br>resource_id (string): resource_id '
                   '(str)<br>max_events (integer, optional): max_events (int, 可选, 默认 20000)',
  'returns_raw': 'Usage includes native usage_name, nullable is_read/is_write, binding_only_observable=false, event identity and color/depth attachments. These are recorded usages, not per-pixel access proof.<br>ok (bool)<br>data (dict): {usage}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'resource_id', 'max_events'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'resource',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'resource_id': {'description': 'resource_id (str)',
                                                  'type': 'string'},
                                  'max_events': {'description': 'max_events (int, 可选, 默认 20000)',
                                                 'type': 'integer'}},
                   'required': ['session_id', 'resource_id'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.resource.list_all',
  'group': '3.5，资源探查 (Resource Inspection & History)',
  'description': '列出捕获中所有资源（Textures/Buffers/Shaders/Pipelines 等），兼容 V3。',
  'parameter_raw': 'session_id (string): session_id (str)<br>types (array): types (list[str], 可选): '
                   "过滤类型，如 ['Texture','Buffer','Shader']；缺省为全部<br>include_unused (boolean): "
                   'include_unused (bool, 可选, 默认 true)<br>kind (string): kind',
  'returns_raw': 'ok (bool)<br>data (dict): {resources}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'types', 'include_unused', 'kind'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'resource',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'types': {'description': 'types (list[str], 可选): 过滤类型，如 '
                                                           "['Texture','Buffer','Shader']；缺省为全部",
                                            'type': 'array',
                                            'items': {'type': 'string'}},
                                  'include_unused': {'description': 'include_unused (bool, 可选, 默认 '
                                                                    'true)',
                                                     'type': 'boolean'},
                                  'kind': {'type': 'string',
                                           'enum': ['all', 'texture', 'buffer', 'descriptor_store'],
                                           'default': 'all'}},
                   'required': ['session_id'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.resource.set_alias',
  'group': '3.5，资源探查 (Resource Inspection & History)',
  'description': '为资源设置一个本地别名，仅影响后续输出/报告，不修改捕获内容。',
  'parameter_raw': 'session_id (string): session_id (str)<br>resource_id (string): resource_id '
                   "(str)<br>alias (string): alias (str): 例如 'GBufferA'/'MainColor' 等",
  'returns_raw': 'ok (bool)<br>data (dict): tool-specific payload<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'resource_id', 'alias'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'resource',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'resource_id': {'description': 'resource_id (str)',
                                                  'type': 'string'},
                                  'alias': {'description': "alias (str): 例如 'GBufferA'/'MainColor' "
                                                           '等',
                                            'type': 'string'}},
                   'required': ['session_id', 'resource_id', 'alias'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['context_metadata'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.session.clear_context',
  'group': '3.17，上下文快照工具 (Context Snapshot Tools)',
  'description': 'Clear an isolated CLI daemon context namespace and its runtime state.',
  'parameter_raw': 'target_context_id (string, optional): target_context_id (str, '
                   'optional)<br>context_id (string, optional): context_id (str, optional): '
                   'current daemon context when omitted',
  'returns_raw': 'ok (bool)<br>data (dict): {context_id, backend, runtime, remote, focus, notes, '
                 'current_session_id, sessions, recovery, limits, updated_at_ms}<br>artifacts '
                 '(list)<br>error (dict|null)<br>meta (dict)<br>projections (dict, optional)',
  'param_names': ['target_context_id', 'context_id'],
  'prerequisites': [],
  'namespace': 'session',
  'input_schema': {'type': 'object',
                   'properties': {'target_context_id': {'description': 'target_context_id (str, '
                                                                       'optional)',
                                                        'type': 'string'},
                                  'context_id': {'description': 'context_id (str, optional): '
                                                                'current daemon context when '
                                                                'omitted',
                                                 'type': 'string'}},
                   'required': [],
                   'additionalProperties': False},
  'scope': 'context',
  'effects': ['lifecycle'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.session.close_preview',
  'group': '3.17，上下文快照工具 (Context Snapshot Tools)',
  'description': 'Close the preview window for the selected context.',
  'parameter_raw': 'context_id (string, optional): context_id (str, optional): current daemon '
                   'context when omitted',
  'returns_raw': 'ok (bool)<br>data (dict): {context_id, '
                 'preview{enabled,state,view_mode,bound_session_id,bound_capture_file_id,bound_event_id,backend,recovered_from_session_id,rebind_count,last_error,display,updated_at_ms}}<br>artifacts '
                 '(list)<br>error (dict|null)<br>meta (dict)<br>projections (dict, optional)',
  'param_names': ['context_id'],
  'prerequisites': [],
  'namespace': 'session',
  'input_schema': {'type': 'object',
                   'properties': {'context_id': {'description': 'context_id (str, optional): '
                                                                'current daemon context when '
                                                                'omitted',
                                                 'type': 'string'}},
                   'required': [],
                   'additionalProperties': False},
  'scope': 'context',
  'effects': ['desktop_window'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.session.create_context',
  'group': '3.17，上下文快照工具 (Context Snapshot Tools)',
  'description': 'Create or initialize an isolated CLI daemon context namespace.',
  'parameter_raw': 'new_context_id (string): new_context_id (str)<br>context_id (string, '
                   'optional): context_id (str, optional): current daemon context when omitted',
  'returns_raw': 'ok (bool)<br>data (dict): {context_id, backend, runtime, remote, focus, notes, '
                 'last_artifacts, current_session_id, sessions, recovery, limits, '
                 'updated_at_ms}<br>artifacts (list)<br>error (dict|null)<br>meta '
                 '(dict)<br>projections (dict, optional)',
  'param_names': ['new_context_id', 'context_id'],
  'prerequisites': [],
  'namespace': 'session',
  'input_schema': {'type': 'object',
                   'properties': {'new_context_id': {'description': 'new_context_id (str)',
                                                     'type': 'string'},
                                  'context_id': {'description': 'context_id (str, optional): '
                                                                'current daemon context when '
                                                                'omitted',
                                                 'type': 'string'}},
                   'required': ['new_context_id'],
                   'additionalProperties': False},
  'scope': 'context',
  'effects': ['lifecycle'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.session.get_context',
  'group': '3.17，上下文快照工具 (Context Snapshot Tools)',
  'description': '读取当前 context 快照与持久化状态索引，返回 runtime、remote、focus、session 表、恢复信息、最近操作与限制配置。',
  'parameter_raw': 'context_id (string, optional): Must identify the current daemon context. session_id (string, optional): Same-context replay session.',
  'returns_raw': 'ok (bool)<br>data (dict): {context_id, backend, session_locator, runtime, '
                 'remote, focus, notes, last_artifacts, '
                 'preview{enabled,state,view_mode,bound_session_id,bound_capture_file_id,bound_event_id,backend,recovered_from_session_id,rebind_count,last_error,display{output_slot,texture_id,texture_format,framebuffer_extent,viewport_rect,scissor_rect,effective_region_rect,region_marker_mode,window_rect,fit_mode,screen_cap_ratio},updated_at_ms}, '
                 'current_session_id, sessions, recovery, limits, active_operation, '
                 'recent_operations, updated_at_ms, remote_capability_matrix, '
                 'remote_context_locality, remote_handle_origin_context, '
                 'remote_handle_reuse_policy}; remote_capability_matrix is state-first for '
                 'get_context and may report not_currently_probed for live shader/debug/replace '
                 'capability probes<br>artifacts (list)<br>error (dict|null)<br>meta '
                 '(dict)<br>projections (dict, optional)',
  'param_names': ['context_id'],
  'prerequisites': [],
  'namespace': 'session',
  'input_schema': {'type': 'object',
                   'properties': {'context_id': {'type': 'string',
                                                 'description': 'Must identify the current daemon '
                                                                'context.'}},
                   'required': [],
                   'additionalProperties': False},
  'scope': 'context',
  'effects': [],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.session.get_replay_events',
  'group': '3.17，上下文快照工具 (Context Snapshot Tools)',
  'description': 'Read the complete discrete action event index of the selected live context '
                 'without changing its event. Events include parent_chain and nullable marker_path. An explicit session_id must belong to the same daemon context.',
  'parameter_raw': 'context_id (string, optional): Must identify the current daemon context.',
  'returns_raw': 'ok (bool)<br>data (dict): {data, error}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['context_id', 'session_id'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_replay'],
                     'reason': 'Requires an open replay'}],
  'namespace': 'session',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'type': 'string', 'description': 'Optional replay session owned by this daemon context; defaults to selected session.'}, 'context_id': {'type': 'string',
                                                 'description': 'Must identify the current daemon '
                                                                'context.'}},
                   'required': [],
                   'additionalProperties': False},
  'scope': 'context',
  'effects': [],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.session.list_contexts',
  'group': '3.17，上下文快照工具 (Context Snapshot Tools)',
  'description': 'List known isolated CLI daemon context namespaces.',
  'parameter_raw': 'context_id (string, optional): context_id (str, optional): current daemon '
                   'context when omitted',
  'returns_raw': 'ok (bool)<br>data (dict): {context_id, contexts: [{context_id, backend, '
                 'session_locator, current_session_id, current_capture_file_id, session_count, '
                 'capture_count, updated_at_ms}]}<br>artifacts (list)<br>error (dict|null)<br>meta '
                 '(dict)<br>projections (dict, optional)',
  'param_names': ['context_id'],
  'prerequisites': [],
  'namespace': 'session',
  'input_schema': {'type': 'object',
                   'properties': {'context_id': {'description': 'context_id (str, optional): '
                                                                'current daemon context when '
                                                                'omitted',
                                                 'type': 'string'}},
                   'required': [],
                   'additionalProperties': False},
  'scope': 'context',
  'effects': [],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.session.list_sessions',
  'group': '3.17，上下文快照工具 (Context Snapshot Tools)',
  'description': '列出当前 context 下的持久化 session 表、当前选中 session 与恢复摘要。',
  'parameter_raw': 'context_id (string, optional): Must identify the current daemon context.',
  'returns_raw': 'ok (bool)<br>data (dict): {context_id, backend, current_session_id, sessions, '
                 'recovery, limits}<br>artifacts (list)<br>error (dict|null)<br>meta '
                 '(dict)<br>projections (dict, 可选)',
  'param_names': ['context_id'],
  'prerequisites': [],
  'namespace': 'session',
  'input_schema': {'type': 'object',
                   'properties': {'context_id': {'type': 'string',
                                                 'description': 'Must identify the current daemon '
                                                                'context.'}},
                   'required': [],
                   'additionalProperties': False},
  'scope': 'context',
  'effects': [],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.session.observe',
  'group': '3.17，上下文快照工具 (Context Snapshot Tools)',
  'description': 'Atomically apply an event and export its color output without a desktop window; '
                 'missing event observes the current state. Remote device presentation is reported '
                 'separately from PNG export, using a fresh native acknowledgement for the applied event '
                 'and selected texture. No color target clears the native output. Missing native '
                 'capability is unsupported; surface and presentation failures are unavailable.',
  'parameter_raw': 'out_path (string): out_path (str): fresh absolute PNG path<br>event_id '
                   '(integer, optional): event_id (int, optional)<br>final_output (boolean, '
                   'optional): final_output (bool, optional): explicit Present resource selection, '
                   'cannot combine with event_id or target<br>target (object, optional): See '
                   'input_schema for constraints.<br>context_id (string, optional): Must identify '
                   'the current daemon context.',
  'returns_raw': 'ok (bool)<br>data (dict): {context_id, session_id, revision, event_id, image_event_id, '
                 'image_path, target, targets, image_error, remote_display{status: presented|unavailable|'
                 'unsupported|not_applicable, event_id, texture_id, sequence, reason}}. Presented requires '
                 'successful native GPU presentation and a fresh positive sequence. No-color output '
                 'is unavailable with a successful clear sequence when the surface was cleared; '
                 'failures never reuse a prior receipt.<br>artifacts (list)<br>error (dict|null)<br>meta (dict)',
  'param_names': ['out_path', 'event_id', 'final_output', 'target', 'context_id'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_replay'],
                     'reason': 'Requires an open replay'}],
  'namespace': 'session',
  'input_schema': {'type': 'object',
                   'properties': {'out_path': {'description': 'out_path (str): fresh absolute PNG '
                                                              'path',
                                               'type': 'string'},
                                  'event_id': {'description': 'event_id (int, optional)',
                                               'type': 'integer',
                                               'minimum': 0},
                                  'final_output': {'description': 'final_output (bool, optional): '
                                                                  'explicit Present resource '
                                                                  'selection, cannot combine with '
                                                                  'event_id or target',
                                                   'type': 'boolean'},
                                  'target': {'type': 'object',
                                             'properties': {'texture_id': {'type': 'string'},
                                                            'rt_index': {'type': 'integer',
                                                                         'minimum': 0}},
                                             'additionalProperties': False},
                                  'context_id': {'type': 'string',
                                                 'description': 'Must identify the current daemon '
                                                                'context.'}},
                   'required': ['out_path'],
                   'additionalProperties': False},
  'scope': 'context',
  'effects': ['replay_position', 'artifact_write'],
  'evidence_kind': None,
  'path_inputs': [{'name': 'out_path', 'access': 'write'}]},
 {'name': 'rd.session.open_preview',
  'group': '3.17，上下文快照工具 (Context Snapshot Tools)',
  'description': 'Open or rebind the preview window for the selected context session.',
  'parameter_raw': 'session_id (string, optional): session_id (str, optional): must match the '
                   'current context session; otherwise select it first via '
                   '`rd.session.select_session`<br>context_id (string, optional): context_id (str, '
                   'optional): current daemon context when omitted',
  'returns_raw': 'ok (bool)<br>data (dict): {context_id, '
                 'preview{enabled,state,view_mode,bound_session_id,bound_capture_file_id,bound_event_id,backend,recovered_from_session_id,rebind_count,last_error,display{output_slot,texture_id,texture_format,framebuffer_extent,viewport_rect,scissor_rect,effective_region_rect,region_marker_mode,window_rect,fit_mode,screen_cap_ratio},updated_at_ms}}<br>artifacts '
                 '(list)<br>error (dict|null)<br>meta (dict)<br>projections (dict, optional)',
  'param_names': ['session_id', 'context_id'],
  'prerequisites': [],
  'namespace': 'session',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str, optional): must '
                                                                'match the current context '
                                                                'session; otherwise select it '
                                                                'first via '
                                                                '`rd.session.select_session`',
                                                 'type': 'string'},
                                  'context_id': {'description': 'context_id (str, optional): '
                                                                'current daemon context when '
                                                                'omitted',
                                                 'type': 'string'}},
                   'required': [],
                   'additionalProperties': False},
  'scope': 'context',
  'effects': ['desktop_window'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.session.resume',
  'group': '3.17，上下文快照工具 (Context Snapshot Tools)',
  'description': '基于持久化状态尝试恢复当前 context 的本地 `.rdc` session；可选仅校验指定 session 的恢复结果。',
  'parameter_raw': 'session_id (string, optional): session_id (str, 可选): 若给定则在恢复完成后校验该 session '
                   '是否已恢复为 live<br>context_id (string, optional): Must identify the current daemon '
                   'context.',
  'returns_raw': 'ok (bool)<br>data (dict): {context_id, runtime, remote, focus, '
                 'current_session_id, sessions, recovery, limits, recent_operations, '
                 'updated_at_ms}<br>artifacts (list)<br>error (dict|null)<br>meta '
                 '(dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'context_id'],
  'prerequisites': [],
  'namespace': 'session',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str, 可选): '
                                                                '若给定则在恢复完成后校验该 session 是否已恢复为 live',
                                                 'type': 'string'},
                                  'context_id': {'type': 'string',
                                                 'description': 'Must identify the current daemon '
                                                                'context.'}},
                   'required': [],
                   'additionalProperties': False},
  'scope': 'context',
  'effects': ['lifecycle'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.session.select_session',
  'group': '3.17，上下文快照工具 (Context Snapshot Tools)',
  'description': '切换当前 context 的 current session 指针，而不销毁其他已持有的 session。',
  'parameter_raw': 'session_id (string): session_id (str)<br>context_id (string, optional): Must '
                   'identify the current daemon context.',
  'returns_raw': 'ok (bool)<br>data (dict): {context_id, runtime, remote, focus, '
                 'current_session_id, sessions, recovery, limits, recent_operations, '
                 'updated_at_ms}<br>artifacts (list)<br>error (dict|null)<br>meta '
                 '(dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'context_id'],
  'prerequisites': [],
  'namespace': 'session',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'context_id': {'type': 'string',
                                                 'description': 'Must identify the current daemon '
                                                                'context.'}},
                   'required': ['session_id'],
                   'additionalProperties': False},
  'scope': 'context',
  'effects': ['lifecycle'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.session.update_context',
  'group': '3.17，上下文快照工具 (Context Snapshot Tools)',
  'description': '更新当前 context 的 user-owned 字段，例如 focus_pixel、focus_resource_id、focus_shader_id 与 '
                 'notes。',
  'parameter_raw': 'key (string): key (str)<br>value (any, optional): value (json, 可选): 传 null '
                   '表示清除对应 user-owned 字段<br>context_id (string, optional): Must identify the '
                   'current daemon context.',
  'returns_raw': 'ok (bool)<br>data (dict): {context_id, runtime, remote, focus, notes, '
                 'last_artifacts, updated_at_ms}<br>artifacts (list)<br>error (dict|null)<br>meta '
                 '(dict)<br>projections (dict, 可选)',
  'param_names': ['key', 'value', 'context_id'],
  'prerequisites': [],
  'namespace': 'session',
  'input_schema': {'type': 'object',
                   'properties': {'key': {'description': 'key (str)', 'type': 'string'},
                                  'value': {'description': 'value (json, 可选): 传 null 表示清除对应 '
                                                           'user-owned 字段'},
                                  'context_id': {'type': 'string',
                                                 'description': 'Must identify the current daemon '
                                                                'context.'}},
                   'required': ['key'],
                   'additionalProperties': False},
  'scope': 'context',
  'effects': ['context_metadata'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.shader.compile',
  'group': '3.8，Shader 探查、反射与替换 (Shader Inspection & Replacement)',
  'description': '（可选扩展）在 server 侧调用外部编译器（dxc/glslangValidator/metal）编译 shader，返回 binary '
                 '路径；用于构建替换输入。',
  'parameter_raw': 'source_text (string, optional): source_text (str, 可选): inline HLSL/GLSL/MSL '
                   'source text<br>source_path (string, optional): source_path (str, 可选): shader '
                   'source file path; file directory is added to include_dirs<br>stage (string): '
                   'stage (str)<br>entry (string): entry (str)<br>target (string): target (str): '
                   "e.g. 'vs_6_6'/'ps_6_6' or 'spirv1.6'<br>source_encoding (string, optional): "
                   'source_encoding (str, 可选): hlsl/glsl/spirvasm; DXIL/DXBC text is not accepted '
                   'as source<br>defines (object, optional): defines (dict, 可选)<br>include_dirs '
                   '(array, optional): include_dirs (list[str], 可选)<br>additional_args (array, '
                   'optional): additional_args (list[str], 可选)<br>output_path (string, optional): '
                   'output_path (str, 可选)<br>session_id (string): See input_schema for '
                   'constraints.<br>event_id (integer, optional): Replay event; omitted uses the '
                   'owning session current event.',
  'returns_raw': 'ok (bool)<br>data (dict): {session_id, shader_id, entry, target, stage, '
                 'source_kind, resolved_source_path, include_dirs, source_encoding, '
                 'supported_source_encodings, runtime_replacement_supported, '
                 'runtime_replacement_reason, messages, compiler_messages, edit_plan, saved_path?, '
                 'artifact_path?, byte_size?}<br>artifacts (list)<br>error (dict|null): compile '
                 'validation/build failures include source_kind, resolved_source_path, '
                 'include_dirs, entry, target, and failure_stage. Unsupported source encoding '
                 'returns shader_compile_encoding_unsupported. DXIL/DXBC captured disassembly text '
                 'is not accepted as editable source.<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['source_text',
                  'source_path',
                  'stage',
                  'entry',
                  'target',
                  'source_encoding',
                  'defines',
                  'include_dirs',
                  'additional_args',
                  'output_path',
                  'session_id',
                  'event_id'],
  'prerequisites': [],
  'namespace': 'shader',
  'input_schema': {'type': 'object',
                   'properties': {'source_text': {'description': 'source_text (str, 可选): inline '
                                                                 'HLSL/GLSL/MSL source text',
                                                  'type': 'string'},
                                  'source_path': {'description': 'source_path (str, 可选): shader '
                                                                 'source file path; file directory '
                                                                 'is added to include_dirs',
                                                  'type': 'string'},
                                  'stage': {'description': 'stage (str)', 'type': 'string'},
                                  'entry': {'description': 'entry (str)', 'type': 'string'},
                                  'target': {'description': "target (str): e.g. 'vs_6_6'/'ps_6_6' "
                                                            "or 'spirv1.6'",
                                             'type': 'string'},
                                  'source_encoding': {'description': 'source_encoding (str, 可选): '
                                                                     'hlsl/glsl/spirvasm; '
                                                                     'DXIL/DXBC text is not '
                                                                     'accepted as source',
                                                      'type': 'string'},
                                  'defines': {'description': 'defines (dict, 可选)',
                                              'type': 'object'},
                                  'include_dirs': {'description': 'include_dirs (list[str], 可选)',
                                                   'type': 'array',
                                                   'items': {'type': 'string'}},
                                  'additional_args': {'description': 'additional_args (list[str], '
                                                                     '可选)',
                                                      'type': 'array',
                                                      'items': {'type': 'string'}},
                                  'output_path': {'description': 'output_path (str, 可选)',
                                                  'type': 'string'},
                                  'session_id': {'type': 'string'},
                                  'event_id': {'type': 'integer',
                                               'minimum': 0,
                                               'description': 'Replay event; omitted uses the '
                                                              'owning session current event.'}},
                   'required': ['session_id', 'stage', 'entry', 'target'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position', 'artifact_write'],
  'evidence_kind': None,
  'path_inputs': [{'name': 'source_path', 'access': 'read'},
                  {'name': 'include_dirs', 'access': 'read_directory'},
                  {'name': 'output_path', 'access': 'write'}]},
 {'name': 'rd.shader.debug_start',
  'group': '3.9，Shader Debugger 与像素/顶点级调试 (Shader Debugging)',
  'description': '启动 shader debugger（默认 pixel），在 remote replay 下会先读取 remote capability matrix；如果当前 '
                 'backend/session 明确不支持 debug，则在创建 trace 前直接 truthful-fail。',
  'parameter_raw': 'session_id (string): session_id (str)<br>mode (string, optional): mode (str, '
                   "可选, 默认 'pixel'): 当前正式支持 `pixel`；传入其他 mode 会返回结构化 `validation_error`，并在 details "
                   '中附带 `supported_modes` / `requested_mode` / `failure_stage` / '
                   '`failure_reason`<br>event_id (integer, optional): event_id (int, 可选): 缺省为当前 '
                   'active event<br>params (object): params (dict): pixel 模式下使用 {x, y, sample?, '
                   'target?, view?, primitive?}<br>timeout_ms (integer, optional): timeout_ms '
                   '(int, 可选, 默认 10000)<br>context_id (string, optional): context_id (str, '
                   'optional): choose the context to use; defaults to the current daemon context',
  'returns_raw': 'ok (bool)<br>data (dict): {shader_debug_id, initial_state, resolved_context, '
                 'resolved_event_id, pixel_history_summary, selected_target_source, failure_stage, '
                 'failure_reason, attempts}<br>artifacts (list)<br>error (dict|null): remote '
                 'backend/session 明确不支持时，优先返回 capability-style 错误，而不是等到 trace 创建后才报 '
                 '`debugger_handle_missing`<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'mode', 'event_id', 'params', 'timeout_ms', 'context_id'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'shader',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'mode': {'description': "mode (str, 可选, 默认 'pixel'): 当前正式支持 "
                                                          '`pixel`；传入其他 mode 会返回结构化 '
                                                          '`validation_error`，并在 details 中附带 '
                                                          '`supported_modes` / `requested_mode` / '
                                                          '`failure_stage` / `failure_reason`',
                                           'type': 'string'},
                                  'event_id': {'description': 'event_id (int, 可选): 缺省为当前 active '
                                                              'event',
                                               'type': 'integer',
                                               'minimum': 0},
                                  'params': {'description': 'params (dict): pixel 模式下使用 {x, y, '
                                                            'sample?, target?, view?, primitive?}',
                                             'type': 'object'},
                                  'timeout_ms': {'description': 'timeout_ms (int, 可选, 默认 10000)',
                                                 'type': 'integer'},
                                  'context_id': {'description': 'context_id (str, optional): '
                                                                'choose the context to use; '
                                                                'defaults to the current daemon '
                                                                'context',
                                                 'type': 'string'}},
                   'required': ['session_id', 'params'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['shader_debug', 'replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.shader.edit_and_replace',
  'group': '3.8，Shader 探查、反射与替换 (Shader Inspection & Replacement)',
  'description': '在当前 Replay Session 中替换 shader；支持 `event_id + stage` 与 `event_id + stage + '
                 'shader_id` 两种入口，显式 `shader_id` 会优先作为绑定 identity 校验。',
  'parameter_raw': 'session_id (string): session_id (str)<br>stage (string): stage '
                   '(str)<br>event_id (integer, optional): event_id (int, 可选)<br>shader_id '
                   '(string, optional): shader_id (str, 可选): expected bound shader identity<br>ops '
                   '(array, optional): ops (list, 可选): structured patch ops<br>source_text '
                   '(string, optional): source_text (str, 可选): full replacement source '
                   'text<br>source_path (string, optional): source_path (str, 可选): full '
                   'replacement source file path<br>entry (string, optional): entry (str, required '
                   'for full HLSL/GLSL replacement unless reflection provides it)<br>target '
                   '(string, optional): target (str, required for full HLSL/GLSL replacement, e.g. '
                   'ps_6_6)<br>source_encoding (string, optional): source_encoding (str, 可选, e.g. '
                   'hlsl/glsl/spirvasm)<br>diff_text (string, optional): diff_text (str, '
                   '可选)<br>emit_patch_artifacts (boolean, optional): emit_patch_artifacts (bool, '
                   '可选)<br>output_dir (string, optional): output_dir (str, '
                   '可选)<br>expected_source_hash (string, optional): See input_schema for '
                   'constraints.<br>include_dirs (array, optional): See input_schema for '
                   'constraints.<br>intent (string, optional): See input_schema for '
                   'constraints.<br>max_diff_ops (integer, optional): See input_schema for '
                   'constraints.<br>preserve_outputs (boolean, optional): See input_schema for '
                   'constraints.<br>replacement_id (string, optional): See input_schema for '
                   'constraints.<br>source_target (string, optional): See input_schema for '
                   'constraints.',
  'returns_raw': "ok (bool)<br>data (dict): {replacement_id, status='applied'|'noop', "
                 'resolved_event_id, messages, edit_plan, replacement{edit_plan, compile{encoding, '
                 'disassembly_target, entry_point, compile_flags}, artifacts{source_before, '
                 'source_after, patch_diff}}}<br>artifacts (list): when emit_patch_artifacts=true '
                 'or output_dir is provided, includes before/after/diff text artifacts<br>error '
                 '(dict|null): DXIL/DXBC disassembly remains read-only '
                 '(captured_source_editable=false), but user-provided HLSL/GLSL full replacement '
                 'can compile then ReplaceResource when runtime_full_replace_supported=true. Build '
                 'failures do not call ReplaceResource. Replace failures include '
                 'replacement_attempted, cleanup_attempted, context_preserved, failure_stage, and '
                 'failure_reason.<br>meta (dict)<br>projections (dict, optional)',
  'param_names': ['session_id',
                  'stage',
                  'event_id',
                  'shader_id',
                  'ops',
                  'source_text',
                  'source_path',
                  'entry',
                  'target',
                  'source_encoding',
                  'diff_text',
                  'emit_patch_artifacts',
                  'output_dir',
                  'expected_source_hash',
                  'include_dirs',
                  'intent',
                  'max_diff_ops',
                  'preserve_outputs',
                  'replacement_id',
                  'source_target'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'shader',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'stage': {'description': 'stage (str)', 'type': 'string'},
                                  'event_id': {'description': 'event_id (int, 可选)',
                                               'type': 'integer',
                                               'minimum': 0},
                                  'shader_id': {'description': 'shader_id (str, 可选): expected '
                                                               'bound shader identity',
                                                'type': 'string'},
                                  'ops': {'description': 'ops (list, 可选): structured patch ops',
                                          'type': 'array',
                                          'items': {}},
                                  'source_text': {'description': 'source_text (str, 可选): full '
                                                                 'replacement source text',
                                                  'type': 'string'},
                                  'source_path': {'description': 'source_path (str, 可选): full '
                                                                 'replacement source file path',
                                                  'type': 'string'},
                                  'entry': {'description': 'entry (str, required for full '
                                                           'HLSL/GLSL replacement unless '
                                                           'reflection provides it)',
                                            'type': 'string'},
                                  'target': {'description': 'target (str, required for full '
                                                            'HLSL/GLSL replacement, e.g. ps_6_6)',
                                             'type': 'string'},
                                  'source_encoding': {'description': 'source_encoding (str, 可选, '
                                                                     'e.g. hlsl/glsl/spirvasm)',
                                                      'type': 'string'},
                                  'diff_text': {'description': 'diff_text (str, 可选)',
                                                'type': 'string'},
                                  'emit_patch_artifacts': {'description': 'emit_patch_artifacts '
                                                                          '(bool, 可选)',
                                                           'type': 'boolean'},
                                  'output_dir': {'description': 'output_dir (str, 可选)',
                                                 'type': 'string'},
                                  'expected_source_hash': {'type': 'string'},
                                  'include_dirs': {'type': 'array', 'items': {'type': 'string'}},
                                  'intent': {'type': 'string'},
                                  'max_diff_ops': {'type': 'integer', 'minimum': 0},
                                  'preserve_outputs': {'type': 'boolean'},
                                  'replacement_id': {'type': 'string'},
                                  'source_target': {'type': 'string'}},
                   'required': ['session_id', 'stage'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['shader_replacement', 'replay_position', 'artifact_write'],
  'evidence_kind': 'intervention',
  'path_inputs': [{'name': 'source_path', 'access': 'read'},
                  {'name': 'output_dir', 'access': 'write'},
                  {'name': 'include_dirs', 'access': 'read_directory'}]},
 {'name': 'rd.shader.extract_binary',
  'group': '3.8，Shader 探查、反射与替换 (Shader Inspection & Replacement)',
  'description': '提取 shader 的二进制 blob（DXIL/DXBC/SPIR-V 等），并保存为文件。',
  'parameter_raw': 'session_id (string): session_id (str)<br>shader_id (string, optional): '
                   'shader_id (str)<br>output_path (string, optional): output_path (str, '
                   "可选)<br>container (string, optional): container (str, 可选): `'auto'<br>event_id "
                   '(integer, optional): Replay event; omitted uses the owning session current '
                   'event.<br>stage (string, optional): See input_schema for '
                   'constraints.<br>as_base64 (boolean, optional): See input_schema for '
                   'constraints.',
  'returns_raw': 'ok (bool)<br>data (dict): tool-specific payload<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id',
                  'shader_id',
                  'output_path',
                  'container',
                  'event_id',
                  'stage',
                  'as_base64'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'shader',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'shader_id': {'description': 'shader_id (str)', 'type': 'string'},
                                  'output_path': {'description': 'output_path (str, 可选)',
                                                  'type': 'string'},
                                  'container': {'description': "container (str, 可选): `'auto'",
                                                'type': 'string'},
                                  'event_id': {'type': 'integer',
                                               'minimum': 0,
                                               'description': 'Replay event; omitted uses the '
                                                              'owning session current event.'},
                                  'stage': {'type': 'string'},
                                  'as_base64': {'type': 'boolean'}},
                   'required': ['session_id'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position', 'artifact_write'],
  'evidence_kind': None,
  'path_inputs': [{'name': 'output_path', 'access': 'write'}]},
 {'name': 'rd.shader.get_bindpoint_mapping',
  'group': '3.8，Shader 探查、反射与替换 (Shader Inspection & Replacement)',
  'description': '获取 shader 资源绑定点映射（register/space/binding -> semantic meaning）。',
  'parameter_raw': 'session_id (string): session_id (str)<br>shader_id (string, optional): '
                   'shader_id (str)<br>event_id (integer, optional): Replay event; omitted uses '
                   'the owning session current event.<br>stage (string, optional): See '
                   'input_schema for constraints.',
  'returns_raw': 'ok (bool)<br>data (dict): {mapping}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'shader_id', 'event_id', 'stage'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'shader',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'shader_id': {'description': 'shader_id (str)', 'type': 'string'},
                                  'event_id': {'type': 'integer',
                                               'minimum': 0,
                                               'description': 'Replay event; omitted uses the '
                                                              'owning session current event.'},
                                  'stage': {'type': 'string'}},
                   'required': ['session_id'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.shader.get_constant_block_layout',
  'group': '3.8，Shader 探查、反射与替换 (Shader Inspection & Replacement)',
  'description': '读取常量块布局（variables、offset、type、array、matrix layout）。',
  'parameter_raw': 'session_id (string): session_id (str)<br>shader_id (string, optional): '
                   "shader_id (str)<br>block_name_or_index (['string', 'integer']): See "
                   'input_schema for constraints.<br>event_id (integer, optional): Replay event; '
                   'omitted uses the owning session current event.<br>stage (string, optional): '
                   'See input_schema for constraints.',
  'returns_raw': 'ok (bool)<br>data (dict): {layout}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'shader_id', 'block_name_or_index', 'event_id', 'stage'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'shader',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'shader_id': {'description': 'shader_id (str)', 'type': 'string'},
                                  'block_name_or_index': {'type': ['string', 'integer']},
                                  'event_id': {'type': 'integer',
                                               'minimum': 0,
                                               'description': 'Replay event; omitted uses the '
                                                              'owning session current event.'},
                                  'stage': {'type': 'string'}},
                   'required': ['session_id', 'block_name_or_index'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.shader.get_constant_buffer_contents',
  'group': '3.8，Shader 探查、反射与替换 (Shader Inspection & Replacement)',
  'description': '读取指定 stage/slot 的 Constant Buffer 并按反射结构解码变量值（推荐用于专家级核对）。',
  'parameter_raw': 'session_id (string): session_id (str)<br>stage (string): stage (str)<br>slot '
                   '(integer): slot (int)<br>array_index (integer, optional): array_index (int, '
                   '可选, 默认 0): CB array/space 情况<br>max_bytes (integer, optional): max_bytes (int, '
                   '可选, 默认 1048576)<br>flatten (boolean, optional): flatten (bool, 可选, 默认 true): '
                   '是否将嵌套结构摊平成 path->value<br>event_id (integer, optional): Replay event; omitted '
                   'uses the owning session current event.<br>shader_id (string, optional): See '
                   'input_schema for constraints.',
  'returns_raw': 'ok (bool)<br>data (dict): {cbuffer}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id',
                  'stage',
                  'slot',
                  'array_index',
                  'max_bytes',
                  'flatten',
                  'event_id',
                  'shader_id'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'shader',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'stage': {'description': 'stage (str)', 'type': 'string'},
                                  'slot': {'description': 'slot (int)',
                                           'type': 'integer',
                                           'minimum': 0},
                                  'array_index': {'description': 'array_index (int, 可选, 默认 0): CB '
                                                                 'array/space 情况',
                                                  'type': 'integer',
                                                  'minimum': 0},
                                  'max_bytes': {'description': 'max_bytes (int, 可选, 默认 1048576)',
                                                'type': 'integer'},
                                  'flatten': {'description': 'flatten (bool, 可选, 默认 true): '
                                                             '是否将嵌套结构摊平成 path->value',
                                              'type': 'boolean'},
                                  'event_id': {'type': 'integer',
                                               'minimum': 0,
                                               'description': 'Replay event; omitted uses the '
                                                              'owning session current event.'},
                                  'shader_id': {'type': 'string'}},
                   'required': ['session_id', 'stage', 'slot'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.shader.get_debug_state',
  'group': '3.9，Shader Debugger 与像素/顶点级调试 (Shader Debugging)',
  'description': '获取当前 debugger 状态（当前 PC、活跃函数、变量、寄存器等）。',
  'parameter_raw': 'session_id (string): session_id (str)<br>shader_debug_id (string): '
                   'shader_debug_id (str)<br>detail_level (string, optional): detail_level (str, '
                   "可选, 默认 'full'): 'summary' | 'full'<br>event_id (integer, optional): Replay "
                   'event; omitted uses the owning session current event.',
  'returns_raw': 'ok (bool)<br>data (dict): {state}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'shader_debug_id', 'detail_level', 'event_id'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'shader',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'shader_debug_id': {'description': 'shader_debug_id (str)',
                                                      'type': 'string'},
                                  'detail_level': {'description': 'detail_level (str, 可选, 默认 '
                                                                  "'full'): 'summary' | 'full'",
                                                   'type': 'string'},
                                  'event_id': {'type': 'integer',
                                               'minimum': 0,
                                               'description': 'Replay event; omitted uses the '
                                                              'owning session current event.'}},
                   'required': ['session_id', 'shader_debug_id'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.shader.get_disassembly',
  'group': '3.8，Shader 探查、反射与替换 (Shader Inspection & Replacement)',
  'description': '获取指定 shader 的反汇编/IR；event-bound shader 解析与 '
                 '`rd.pipeline.get_shader`、`rd.export.shader_bundle`、`rd.shader.get_reflection`、`rd.shader.edit_and_replace` '
                 '使用同一套绑定逻辑。',
  'parameter_raw': 'session_id (string): session_id (str)<br>shader_id (string, optional): '
                   'shader_id (str)<br>target (string, optional): target (str, 可选): '
                   "`'auto'<br>event_id (integer, optional): Replay event; omitted uses the owning "
                   'session current event.<br>stage (string, optional): See input_schema for '
                   'constraints.',
  'returns_raw': 'ok (bool)<br>data (dict): {disassembly, target, source_encoding, '
                 'is_raw_spirv_asm, source_hash, shader_id, resolved_event_id, '
                 'edit_plan}<br>`edit_plan` describes shader_format, input_kind, can_edit_text, '
                 'can_build, can_replace, requires_toolchain, build_input_kind, '
                 'allowed_edit_inputs, allowed_ops, recommended_next_tool, and blocked_reason. '
                 'DXIL/DXBC disassembly is read-only unless edit_plan reports a buildable source '
                 'path.<br>artifacts (list)<br>error (dict|null): 绑定失败显式返回 '
                 '`shader_binding_lookup_failed` / `shader_stage_mismatch`；当请求 target '
                 '不存在或源码不可取时，显式返回 `shader_disassembly_unavailable` 并带 `failure_stage` / '
                 '`failure_reason`<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'shader_id', 'target', 'event_id', 'stage'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'shader',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'shader_id': {'description': 'shader_id (str)', 'type': 'string'},
                                  'target': {'description': "target (str, 可选): `'auto'",
                                             'type': 'string'},
                                  'event_id': {'type': 'integer',
                                               'minimum': 0,
                                               'description': 'Replay event; omitted uses the '
                                                              'owning session current event.'},
                                  'stage': {'type': 'string'}},
                   'required': ['session_id'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.shader.get_messages',
  'group': '3.8，Shader 探查、反射与替换 (Shader Inspection & Replacement)',
  'description': '获取 RenderDoc 在 shader 编译/替换/调试过程产生的 messages。',
  'parameter_raw': 'session_id (string): session_id (str)<br>severity_min (string, optional): '
                   "severity_min (str, 可选, 默认 'info'): `'debug'<br>event_id (integer, optional): "
                   'Replay event; omitted uses the owning session current event.',
  'returns_raw': 'ok (bool)<br>data (dict): tool-specific payload<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'severity_min', 'event_id'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'shader',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'severity_min': {'description': 'severity_min (str, 可选, 默认 '
                                                                  "'info'): `'debug'",
                                                   'type': 'string'},
                                  'event_id': {'type': 'integer',
                                               'minimum': 0,
                                               'description': 'Replay event; omitted uses the '
                                                              'owning session current event.'}},
                   'required': ['session_id'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.shader.get_reflection',
  'group': '3.8，Shader 探查、反射与替换 (Shader Inspection & Replacement)',
  'description': '获取指定 shader 的反射信息；支持 `event_id + stage` 与 `event_id + stage + shader_id` 两种 '
                 'event-bound 绑定方式，显式 `shader_id` 会优先参与身份校验。',
  'parameter_raw': 'session_id (string): session_id (str)<br>shader_id (string, optional): '
                   'shader_id (str, 可选): 若提供，则必须与请求 event/stage 当前绑定 shader identity 一致<br>stage '
                   '(string, optional): stage (str, 可选): 若未提供 `shader_id`，则与 `event_id` 一起解析当前绑定 '
                   'shader<br>event_id (integer, optional): event_id (int, 可选): 缺省为当前 active '
                   'event<br>include_bindings (boolean, optional): include_bindings (bool, 可选, 默认 '
                   'true)<br>include_constant_blocks (boolean, optional): include_constant_blocks '
                   '(bool, 可选, 默认 true)<br>context_id (string, optional): context_id (str, '
                   'optional): choose the context to use; defaults to the current daemon context',
  'returns_raw': 'ok (bool)<br>data (dict): {reflection, shader_id, '
                 'resolved_event_id}<br>artifacts (list)<br>error (dict|null): 绑定失败显式返回 '
                 '`shader_binding_lookup_failed` / `shader_stage_mismatch` / '
                 '`shader_reflection_unavailable`，不再把所有失败折叠成 `shader_not_bound`<br>meta '
                 '(dict)<br>projections (dict, 可选)',
  'param_names': ['session_id',
                  'shader_id',
                  'stage',
                  'event_id',
                  'include_bindings',
                  'include_constant_blocks',
                  'context_id'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'shader',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'shader_id': {'description': 'shader_id (str, 可选): 若提供，则必须与请求 '
                                                               'event/stage 当前绑定 shader identity '
                                                               '一致',
                                                'type': 'string'},
                                  'stage': {'description': 'stage (str, 可选): 若未提供 `shader_id`，则与 '
                                                           '`event_id` 一起解析当前绑定 shader',
                                            'type': 'string'},
                                  'event_id': {'description': 'event_id (int, 可选): 缺省为当前 active '
                                                              'event',
                                               'type': 'integer',
                                               'minimum': 0},
                                  'include_bindings': {'description': 'include_bindings (bool, 可选, '
                                                                      '默认 true)',
                                                       'type': 'boolean'},
                                  'include_constant_blocks': {'description': 'include_constant_blocks '
                                                                             '(bool, 可选, 默认 true)',
                                                              'type': 'boolean'},
                                  'context_id': {'description': 'context_id (str, optional): '
                                                                'choose the context to use; '
                                                                'defaults to the current daemon '
                                                                'context',
                                                 'type': 'string'}},
                   'required': ['session_id'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.shader.get_source',
  'group': '3.8，Shader 探查、反射与替换 (Shader Inspection & Replacement)',
  'description': '获取 shader 的源码/调试信息（若捕获包含 debug info，例如 PDB/DWARF/source embedding）。',
  'parameter_raw': 'session_id (string): session_id (str)<br>shader_id (string, optional): '
                   'shader_id (str)<br>prefer_original (boolean, optional): prefer_original (bool, '
                   '可选, 默认 true): 优先返回原始源码（若可得）<br>event_id (integer, optional): Replay event; '
                   'omitted uses the owning session current event.<br>stage (string, optional): '
                   'See input_schema for constraints.',
  'returns_raw': 'ok (bool)<br>data (dict): {source, files, source_available, fallback_tool?, '
                 'fallback_args?, edit_plan, failure_stage?, failure_reason?, shader_id, stage, '
                 'resolved_event_id}; when original debug source is unavailable, returns ok=true '
                 'with source_available=false and a format-aware fallback. SPIR-V may recommend '
                 "`rd.shader.get_disassembly` with target='SPIR-V ASM' and "
                 "source_encoding='spirvasm'; DXIL/DXBC recommends read-only disassembly and/or "
                 '`rd.shader.extract_binary` instead of treating disassembly text as replacement '
                 'source.<br>artifacts (list)<br>error (dict|null)<br>meta (dict)<br>projections '
                 '(dict, 可选)',
  'param_names': ['session_id', 'shader_id', 'prefer_original', 'event_id', 'stage'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'shader',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'shader_id': {'description': 'shader_id (str)', 'type': 'string'},
                                  'prefer_original': {'description': 'prefer_original (bool, 可选, '
                                                                     '默认 true): 优先返回原始源码（若可得）',
                                                      'type': 'boolean'},
                                  'event_id': {'type': 'integer',
                                               'minimum': 0,
                                               'description': 'Replay event; omitted uses the '
                                                              'owning session current event.'},
                                  'stage': {'type': 'string'}},
                   'required': ['session_id'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.shader.list_entry_points',
  'group': '3.8，Shader 探查、反射与替换 (Shader Inspection & Replacement)',
  'description': '列出 shader 容器中的 entry points（适用于 DXIL library/多 entry SPIR-V）。',
  'parameter_raw': 'session_id (string): session_id (str)<br>shader_id (string, optional): '
                   'shader_id (str)<br>event_id (integer, optional): Replay event; omitted uses '
                   'the owning session current event.<br>stage (string, optional): See '
                   'input_schema for constraints.',
  'returns_raw': 'ok (bool)<br>data (dict): {entry_points}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'shader_id', 'event_id', 'stage'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'shader',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'shader_id': {'description': 'shader_id (str)', 'type': 'string'},
                                  'event_id': {'type': 'integer',
                                               'minimum': 0,
                                               'description': 'Replay event; omitted uses the '
                                                              'owning session current event.'},
                                  'stage': {'type': 'string'}},
                   'required': ['session_id'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.shader.list_replacements',
  'group': '3.8，Shader 探查、反射与替换 (Shader Inspection & Replacement)',
  'description': '列出当前 session 中已生效的 shader 替换。',
  'parameter_raw': 'session_id (string): session_id (str)<br>event_id (integer, optional): Replay '
                   'event; omitted uses the owning session current event.',
  'returns_raw': 'ok (bool)<br>data (dict): {replacements}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'event_id'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'shader',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'event_id': {'type': 'integer',
                                               'minimum': 0,
                                               'description': 'Replay event; omitted uses the '
                                                              'owning session current event.'}},
                   'required': ['session_id'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.shader.revert_replacement',
  'group': '3.8，Shader 探查、反射与替换 (Shader Inspection & Replacement)',
  'description': '撤销 shader 替换，恢复捕获中的原始 shader。',
  'parameter_raw': 'session_id (string): session_id (str)<br>replacement_id (string): '
                   'replacement_id (str)<br>event_id (integer, optional): Replay event; omitted '
                   'uses the owning session current event.',
  'returns_raw': 'ok (bool)<br>data (dict): tool-specific payload<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'replacement_id', 'event_id'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'shader',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'replacement_id': {'description': 'replacement_id (str)',
                                                     'type': 'string'},
                                  'event_id': {'type': 'integer',
                                               'minimum': 0,
                                               'description': 'Replay event; omitted uses the '
                                                              'owning session current event.'}},
                   'required': ['session_id', 'replacement_id'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['shader_replacement', 'replay_position'],
  'evidence_kind': 'rollback',
  'path_inputs': []},
 {'name': 'rd.texture.compute_stats',
  'group': '3.6，纹理数据访问与分析 (Texture Data Access & Analysis)',
  'description': '用于计算纹理的统计量，包括均值 (mean)、标准差 (stddev)、NaN/Inf 计数以及 0/1 占比等，以便进行快速的健全性检查 (sanity '
                 'check)。',
  'parameter_raw': 'session_id (string): session_id (str)<br>texture_id (string): texture_id '
                   '(str)<br>mip (integer, optional): mip (int, 可选, 默认 0)<br>slice (integer, '
                   'optional): slice (int, 可选, 默认 0)<br>sample (integer, optional): sample (int, '
                   '可选, 默认 0)<br>stride (integer, optional): stride (int, 可选, 默认 1)<br>event_id '
                   '(integer, optional): Replay event; omitted uses the owning session current '
                   'event.',
  'returns_raw': 'data: {stats: {min,max,mean,nan_count,inf_count,channels}, '
                 'resolved_event_id,texture_id,target_metadata}. Channel min/max exclude '
                 'non-finite samples; all-nonfinite channels have null min/max. Unsupported '
                 'packed/compressed formats fail explicitly.',
  'param_names': ['session_id', 'texture_id', 'mip', 'slice', 'sample', 'stride', 'event_id'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'texture',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'texture_id': {'description': 'texture_id (str)',
                                                 'type': 'string'},
                                  'mip': {'description': 'mip (int, 可选, 默认 0)',
                                          'type': 'integer',
                                          'minimum': 0},
                                  'slice': {'description': 'slice (int, 可选, 默认 0)',
                                            'type': 'integer',
                                            'minimum': 0},
                                  'sample': {'description': 'sample (int, 可选, 默认 0)',
                                             'type': 'integer',
                                             'minimum': 0},
                                  'stride': {'description': 'stride (int, 可选, 默认 1)',
                                             'type': 'integer'},
                                  'event_id': {'type': 'integer',
                                               'minimum': 0,
                                               'description': 'Replay event; omitted uses the '
                                                              'owning session current event.'}},
                   'required': ['session_id', 'texture_id'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.texture.diff',
  'group': '3.6，纹理数据访问与分析 (Texture Data Access & Analysis)',
  'description': '用于对比两张纹理 (要求尺寸相同且格式可转换)，并输出差异图以及各项指标，如峰值信噪比 (PSNR)、最大绝对误差 (max error) 和均方误差 '
                 '(mean squared error)。',
  'parameter_raw': 'session_id (string): session_id (str)<br>tex_a (object): See input_schema for '
                   'constraints.<br>tex_b (object): See input_schema for constraints.<br>metric '
                   "(array, optional): metric (list[str], 可选): 指标列表，可选 ['max_abs', 'mse', "
                   "'psnr']<br>event_id (integer, optional): See input_schema for constraints.",
  'returns_raw': 'data: {diff: '
                 '{mse,max_abs,psnr,identical,psnr_peak,psnr_status},event_a,event_b}. Identical '
                 'samples return psnr=null and psnr_status=infinite. Mismatched shapes or '
                 'non-finite samples fail. No files are created.',
  'param_names': ['session_id', 'tex_a', 'tex_b', 'metric', 'event_id'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'texture',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'tex_a': {'type': 'object',
                                            'properties': {'texture_id': {'type': 'string'},
                                                           'subresource': {'type': 'object',
                                                                           'properties': {'mip': {'type': 'integer',
                                                                                                  'minimum': 0},
                                                                                          'slice': {'type': 'integer',
                                                                                                    'minimum': 0},
                                                                                          'sample': {'type': 'integer',
                                                                                                     'minimum': 0}},
                                                                           'additionalProperties': False},
                                                           'event_id': {'type': 'integer',
                                                                        'minimum': 0}},
                                            'required': ['texture_id'],
                                            'additionalProperties': False},
                                  'tex_b': {'type': 'object',
                                            'properties': {'texture_id': {'type': 'string'},
                                                           'subresource': {'type': 'object',
                                                                           'properties': {'mip': {'type': 'integer',
                                                                                                  'minimum': 0},
                                                                                          'slice': {'type': 'integer',
                                                                                                    'minimum': 0},
                                                                                          'sample': {'type': 'integer',
                                                                                                     'minimum': 0}},
                                                                           'additionalProperties': False},
                                                           'event_id': {'type': 'integer',
                                                                        'minimum': 0}},
                                            'required': ['texture_id'],
                                            'additionalProperties': False},
                                  'metric': {'description': 'metric (list[str], 可选): 指标列表，可选 '
                                                            "['max_abs', 'mse', 'psnr']",
                                             'type': 'array',
                                             'items': {'type': 'string'}},
                                  'event_id': {'type': 'integer', 'minimum': 0}},
                   'required': ['session_id', 'tex_a', 'tex_b'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.texture.get_data',
  'group': '3.6，纹理数据访问与分析 (Texture Data Access & Analysis)',
  'description': '用于读取纹理子资源的数值 readback 容器。默认返回 `.npz` artifact，供后续统计、像素分析或离线数值处理；它不是图片导出接口。',
  'parameter_raw': 'session_id (string): session_id (str)<br>texture_id (string): texture_id '
                   '(str): 纹理资源 ID<br>event_id (integer): Current-state event to read; mutually '
                   'exclusive with capture_initial.<br>subresource (object): '
                   'subresource<br>output_path (string): output_path (str, 可选): 若提供则必须使用 `.npz` '
                   '扩展名<br>as_base64 (boolean): as_base64 (bool, 可选): 同时返回 `.npz` 容器的 base64 '
                   '文本<br>context_id (string): context_id (str, optional): choose the context to '
                   'use; defaults to the current daemon context<br>state (string): Recorded '
                   'frame-initial contents or current/requested event; reads restore the original '
                   'replay event.<br>representation (string): Numeric NPZ or original packed raw '
                   'bytes (.bin); raw supports depth/compressed formats without numeric decoding.',
  'returns_raw': 'data: resource identity, byte_size, state, resolved_event_id, restored_event_id, '
                 'replay_state_restored=true, initial_provenance; base64 when requested (1 MiB '
                 'limit, no automatic artifact), otherwise explicit output/artifact. Initial '
                 'provenance unavailable, failed/incomplete read and restoration failure are '
                 'distinct errors. Restoration failure requires closing and reopening the session.',
  'param_names': ['session_id',
                  'texture_id',
                  'event_id',
                  'subresource',
                  'output_path',
                  'as_base64',
                  'context_id',
                  'state',
                  'representation'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'texture',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'texture_id': {'description': 'texture_id (str): 纹理资源 ID',
                                                 'type': 'string'},
                                  'event_id': {'type': 'integer',
                                               'minimum': 1,
                                               'description': 'Current-state event to read; '
                                                              'mutually exclusive with '
                                                              'capture_initial.'},
                                  'subresource': {'type': 'object',
                                                  'properties': {'mip': {'type': 'integer',
                                                                         'minimum': 0},
                                                                 'slice': {'type': 'integer',
                                                                           'minimum': 0},
                                                                 'sample': {'type': 'integer',
                                                                            'minimum': 0}},
                                                  'additionalProperties': False},
                                  'output_path': {'description': 'output_path (str, 可选): 若提供则必须使用 '
                                                                 '`.npz` 扩展名',
                                                  'type': 'string'},
                                  'as_base64': {'description': 'as_base64 (bool, 可选): 同时返回 `.npz` '
                                                               '容器的 base64 文本',
                                                'type': 'boolean'},
                                  'context_id': {'description': 'context_id (str, optional): '
                                                                'choose the context to use; '
                                                                'defaults to the current daemon '
                                                                'context',
                                                 'type': 'string'},
                                  'state': {'type': 'string',
                                            'enum': ['current', 'capture_initial'],
                                            'default': 'current',
                                            'description': 'Recorded frame-initial contents or '
                                                           'current/requested event; reads restore '
                                                           'the original replay event.'},
                                  'representation': {'type': 'string',
                                                     'enum': ['numeric', 'raw'],
                                                     'default': 'numeric',
                                                     'description': 'Numeric NPZ or original '
                                                                    'packed raw bytes (.bin); raw '
                                                                    'supports depth/compressed '
                                                                    'formats without numeric '
                                                                    'decoding.'}},
                   'required': ['session_id', 'texture_id'],
                   'additionalProperties': False,
                   'not': {'required': ['state', 'event_id'],
                           'properties': {'state': {'enum': ['capture_initial']}}}},
  'scope': 'replay',
  'effects': ['replay_position_temporary', 'artifact_write'],
  'evidence_kind': None,
  'path_inputs': [{'name': 'output_path', 'access': 'write'}]},
 {'name': 'rd.texture.get_histogram',
  'group': '3.6，纹理数据访问与分析 (Texture Data Access & Analysis)',
  'description': '用于计算纹理子资源的直方图。',
  'parameter_raw': 'session_id (string): session_id (str)<br>texture_id (string): texture_id '
                   '(str)<br>mip (integer, optional): mip (int, 可选, 默认 0)<br>slice (integer, '
                   'optional): slice (int, 可选, 默认 0)<br>channels (string, optional): channels '
                   "(str, 可选, 默认 'r')<br>bins (integer, optional): bins (int, 可选, 默认 256)<br>range "
                   '(object, optional): range (dict, 可选): 包含 {min, max} (如果缺省则自动计算)<br>event_id '
                   '(integer, optional): Replay event; omitted uses the owning session current '
                   'event.<br>sample (integer, optional): See input_schema for constraints.',
  'returns_raw': 'ok (bool)<br>data (dict): {histogram, bin_edges}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id',
                  'texture_id',
                  'mip',
                  'slice',
                  'channels',
                  'bins',
                  'range',
                  'event_id',
                  'sample'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'texture',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'texture_id': {'description': 'texture_id (str)',
                                                 'type': 'string'},
                                  'mip': {'description': 'mip (int, 可选, 默认 0)',
                                          'type': 'integer',
                                          'minimum': 0},
                                  'slice': {'description': 'slice (int, 可选, 默认 0)',
                                            'type': 'integer',
                                            'minimum': 0},
                                  'channels': {'description': "channels (str, 可选, 默认 'r')",
                                               'type': 'string'},
                                  'bins': {'description': 'bins (int, 可选, 默认 256)',
                                           'type': 'integer'},
                                  'range': {'description': 'range (dict, 可选): 包含 {min, max} '
                                                           '(如果缺省则自动计算)',
                                            'type': 'object'},
                                  'event_id': {'type': 'integer',
                                               'minimum': 0,
                                               'description': 'Replay event; omitted uses the '
                                                              'owning session current event.'},
                                  'sample': {'type': 'integer', 'minimum': 0}},
                   'required': ['session_id', 'texture_id'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.texture.get_pixel_history',
  'group': '3.6，纹理数据访问与分析 (Texture Data Access & Analysis)',
  'description': '用于获取当前活动事件 (active event) 下某个像素的历史信息，即哪些绘制调用 (drawcall) 或调度 (dispatch) 影响了该像素。',
  'parameter_raw': 'session_id (string): session_id (str)<br>texture_id (string, optional): '
                   'texture_id (str): 通常为当前渲染目标 (RT)<br>x (integer): x (int)<br>y (integer): y '
                   '(int)<br>mip (integer, optional): mip (int, 可选, 默认 0)<br>slice (integer, '
                   'optional): slice (int, 可选, 默认 0)<br>sample (integer, optional): sample (int, '
                   '可选, 默认 0)<br>include_shaders (boolean, optional): include_shaders (bool, 可选, '
                   '默认 true)<br>target (object, optional): See input_schema for '
                   'constraints.<br>event_id (integer, optional): Replay event; omitted uses the '
                   'owning session current event.',
  'returns_raw': 'ok (bool)<br>data (dict): {history}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id',
                  'texture_id',
                  'x',
                  'y',
                  'mip',
                  'slice',
                  'sample',
                  'include_shaders',
                  'target',
                  'event_id'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'texture',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'texture_id': {'description': 'texture_id (str): 通常为当前渲染目标 (RT)',
                                                 'type': 'string'},
                                  'x': {'description': 'x (int)', 'type': 'integer', 'minimum': 0},
                                  'y': {'description': 'y (int)', 'type': 'integer', 'minimum': 0},
                                  'mip': {'description': 'mip (int, 可选, 默认 0)',
                                          'type': 'integer',
                                          'minimum': 0},
                                  'slice': {'description': 'slice (int, 可选, 默认 0)',
                                            'type': 'integer',
                                            'minimum': 0},
                                  'sample': {'description': 'sample (int, 可选, 默认 0)',
                                             'type': 'integer',
                                             'minimum': 0},
                                  'include_shaders': {'description': 'include_shaders (bool, 可选, '
                                                                     '默认 true)',
                                                      'type': 'boolean'},
                                  'target': {'type': 'object',
                                             'properties': {'texture_id': {'type': 'string'},
                                                            'rt_index': {'type': 'integer',
                                                                         'minimum': 0}},
                                             'additionalProperties': False},
                                  'event_id': {'type': 'integer',
                                               'minimum': 0,
                                               'description': 'Replay event; omitted uses the '
                                                              'owning session current event.'}},
                   'required': ['session_id', 'x', 'y'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.texture.get_pixel_value',
  'group': '3.6，纹理数据访问与分析 (Texture Data Access & Analysis)',
  'description': '用于读取纹理在指定像素坐标处的值。该值将自动按照纹理格式解码为 float4 或 int4。',
  'parameter_raw': 'session_id (string): session_id (str)<br>texture_id (string): texture_id '
                   '(str)<br>x (integer): x (int)<br>y (integer): y (int)<br>mip (integer, '
                   'optional): mip (int, 可选, 默认 0)<br>slice (integer, optional): slice (int, 可选, '
                   '默认 0)<br>sample (integer, optional): sample (int, 可选, 默认 0)<br>as_type '
                   "(string, optional): as_type (str, 可选, 默认 'float'): 返回值类型，可选 'float', 'uint', "
                   "'int'<br>event_id (integer, optional): Replay event; omitted uses the owning "
                   'session current event.',
  'returns_raw': 'ok (bool)<br>data (dict): {value}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id',
                  'texture_id',
                  'x',
                  'y',
                  'mip',
                  'slice',
                  'sample',
                  'as_type',
                  'event_id'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'texture',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'texture_id': {'description': 'texture_id (str)',
                                                 'type': 'string'},
                                  'x': {'description': 'x (int)', 'type': 'integer', 'minimum': 0},
                                  'y': {'description': 'y (int)', 'type': 'integer', 'minimum': 0},
                                  'mip': {'description': 'mip (int, 可选, 默认 0)',
                                          'type': 'integer',
                                          'minimum': 0},
                                  'slice': {'description': 'slice (int, 可选, 默认 0)',
                                            'type': 'integer',
                                            'minimum': 0},
                                  'sample': {'description': 'sample (int, 可选, 默认 0)',
                                             'type': 'integer',
                                             'minimum': 0},
                                  'as_type': {'description': "as_type (str, 可选, 默认 'float'): "
                                                             "返回值类型，可选 'float', 'uint', 'int'",
                                              'type': 'string'},
                                  'event_id': {'type': 'integer',
                                               'minimum': 0,
                                               'description': 'Replay event; omitted uses the '
                                                              'owning session current event.'}},
                   'required': ['session_id', 'texture_id', 'x', 'y'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.texture.get_region_values',
  'group': '3.6，纹理数据访问与分析 (Texture Data Access & Analysis)',
  'description': '用于读取纹理中一个矩形区域内的像素值，常用于局部统计分析、查找 NaN 或 Inf 值。',
  'parameter_raw': 'session_id (string): session_id (str)<br>texture_id (string): texture_id '
                   '(str)<br>rect (object): rect (dict): 包含 {x, y, w, h}<br>mip (integer, '
                   'optional): mip (int, 可选, 默认 0)<br>slice (integer, optional): slice (int, 可选, '
                   '默认 0)<br>sample (integer, optional): sample (int, 可选, 默认 0)<br>stride '
                   '(integer, optional): stride (int, 可选, 默认 1): 采样步长，大于 1 可降低处理成本<br>as_type '
                   "(string, optional): as_type (str, 可选, 默认 'float')<br>event_id (integer, "
                   'optional): Replay event; omitted uses the owning session current event.',
  'returns_raw': 'ok (bool)<br>data (dict): {values}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id',
                  'texture_id',
                  'rect',
                  'mip',
                  'slice',
                  'sample',
                  'stride',
                  'as_type',
                  'event_id'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'texture',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'texture_id': {'description': 'texture_id (str)',
                                                 'type': 'string'},
                                  'rect': {'description': 'rect (dict): 包含 {x, y, w, h}',
                                           'type': 'object'},
                                  'mip': {'description': 'mip (int, 可选, 默认 0)',
                                          'type': 'integer',
                                          'minimum': 0},
                                  'slice': {'description': 'slice (int, 可选, 默认 0)',
                                            'type': 'integer',
                                            'minimum': 0},
                                  'sample': {'description': 'sample (int, 可选, 默认 0)',
                                             'type': 'integer',
                                             'minimum': 0},
                                  'stride': {'description': 'stride (int, 可选, 默认 1): 采样步长，大于 1 '
                                                            '可降低处理成本',
                                             'type': 'integer'},
                                  'as_type': {'description': "as_type (str, 可选, 默认 'float')",
                                              'type': 'string'},
                                  'event_id': {'type': 'integer',
                                               'minimum': 0,
                                               'description': 'Replay event; omitted uses the '
                                                              'owning session current event.'}},
                   'required': ['session_id', 'texture_id', 'rect'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position', 'artifact_write'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.texture.render_overlay',
  'group': '3.6，纹理数据访问与分析 (Texture Data Access & Analysis)',
  'description': '用于将叠加层 (overlay) 渲染到纹理上并导出，例如绘制调用高亮、线框、视口/裁剪 (viewport/scissor) 或过度绘制 (quad '
                 'overdraw) 等。',
  'parameter_raw': 'session_id (string): session_id (str)<br>texture_id (string): texture_id '
                   "(str)<br>overlay (string): overlay (str): 叠加层类型，可选 'None', 'Drawcall', "
                   "'Wireframe', 'ViewportScissor', 'Overdraw'<br>event_id (integer, optional): "
                   'event_id (int, 可选): 叠加层关联的事件 ID<br>output_path (string, optional): output_path '
                   '(str, 可选)<br>image_format (string, optional): image_format (str, 可选, 默认 '
                   "'png')<br>channels (string, optional): See input_schema for "
                   'constraints.<br>file_format (string, optional): See input_schema for '
                   'constraints.<br>flip_y (boolean, optional): See input_schema for '
                   'constraints.<br>include_alpha (boolean, optional): See input_schema for '
                   'constraints.',
  'returns_raw': 'ok (bool)<br>data (dict): {image_path}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id',
                  'texture_id',
                  'overlay',
                  'event_id',
                  'output_path',
                  'image_format',
                  'channels',
                  'file_format',
                  'flip_y',
                  'include_alpha'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'texture',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str)',
                                                 'type': 'string'},
                                  'texture_id': {'description': 'texture_id (str)',
                                                 'type': 'string'},
                                  'overlay': {'description': "overlay (str): 叠加层类型，可选 'None', "
                                                             "'Drawcall', 'Wireframe', "
                                                             "'ViewportScissor', 'Overdraw'",
                                              'type': 'string'},
                                  'event_id': {'description': 'event_id (int, 可选): 叠加层关联的事件 ID',
                                               'type': 'integer',
                                               'minimum': 0},
                                  'output_path': {'description': 'output_path (str, 可选)',
                                                  'type': 'string'},
                                  'image_format': {'description': 'image_format (str, 可选, 默认 '
                                                                  "'png')",
                                                   'type': 'string'},
                                  'channels': {'type': 'string'},
                                  'file_format': {'type': 'string'},
                                  'flip_y': {'type': 'boolean'},
                                  'include_alpha': {'type': 'boolean'}},
                   'required': ['session_id', 'texture_id', 'overlay'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position', 'artifact_write'],
  'evidence_kind': None,
  'path_inputs': [{'name': 'output_path', 'access': 'write'}]},
 {'name': 'rd.util.cleanup_artifacts',
  'group': '3.16，通用辅助工具 (Utilities, Optional)',
  'description': '根据指定条件（如会话、前缀、时间或大小阈值）清理 artifacts。',
  'parameter_raw': 'session_id (string, optional): session_id (str, 可选): 会话 ID<br>older_than_ms '
                   '(integer, optional): older_than_ms (int, 可选): 清理早于指定毫秒数的 artifacts<br>prefix '
                   '(string, optional): prefix (str, 可选): 用于过滤 artifacts 路径的前缀<br>max_total_bytes '
                   '(integer, optional): max_total_bytes (int, 可选): 清理 artifacts 直到总大小低于指定字节数',
  'returns_raw': 'ok (bool)<br>data (dict): {deleted, freed_bytes}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'older_than_ms', 'prefix', 'max_total_bytes'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'util',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str, 可选): 会话 ID',
                                                 'type': 'string'},
                                  'older_than_ms': {'description': 'older_than_ms (int, 可选): '
                                                                   '清理早于指定毫秒数的 artifacts',
                                                    'type': 'integer'},
                                  'prefix': {'description': 'prefix (str, 可选): 用于过滤 artifacts '
                                                            '路径的前缀',
                                             'type': 'string'},
                                  'max_total_bytes': {'description': 'max_total_bytes (int, 可选): '
                                                                     '清理 artifacts 直到总大小低于指定字节数',
                                                      'type': 'integer'}},
                   'required': [],
                   'additionalProperties': False},
  'scope': 'global',
  'effects': ['artifact_delete'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.util.diff_images',
  'group': '3.16，通用辅助工具 (Utilities, Optional)',
  'description': '对比两张图片（支持 PNG、JPEG、EXR 格式），输出差异图及相关指标，如 PSNR、SSIM 和最大绝对误差。',
  'parameter_raw': 'image_a_path (string): image_a_path (str): 第一张图片的文件路径<br>image_b_path '
                   '(string): image_b_path (str): 第二张图片的文件路径<br>metrics (array, optional): metrics '
                   "(list[str], 可选): 需要计算的指标列表，例如 ['psnr', 'ssim', 'max_abs', "
                   "'mse']<br>output_path (string, optional): output_path (str, 可选): 差异图的输出路径",
  'returns_raw': 'ok (bool)<br>data (dict): {metrics, diff_image_path}<br>artifacts '
                 '(list)<br>error (dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['image_a_path', 'image_b_path', 'metrics', 'output_path'],
  'prerequisites': [],
  'namespace': 'util',
  'input_schema': {'type': 'object',
                   'properties': {'image_a_path': {'description': 'image_a_path (str): 第一张图片的文件路径',
                                                   'type': 'string'},
                                  'image_b_path': {'description': 'image_b_path (str): 第二张图片的文件路径',
                                                   'type': 'string'},
                                  'metrics': {'description': 'metrics (list[str], 可选): '
                                                             "需要计算的指标列表，例如 ['psnr', 'ssim', "
                                                             "'max_abs', 'mse']",
                                              'type': 'array',
                                              'items': {'type': 'string'}},
                                  'output_path': {'description': 'output_path (str, 可选): 差异图的输出路径',
                                                  'type': 'string'}},
                   'required': ['image_a_path', 'image_b_path'],
                   'additionalProperties': False},
  'scope': 'global',
  'effects': ['artifact_write'],
  'evidence_kind': None,
  'path_inputs': [{'name': 'image_a_path', 'access': 'read'},
                  {'name': 'image_b_path', 'access': 'read'},
                  {'name': 'output_path', 'access': 'write'}]},
 {'name': 'rd.util.list_artifacts',
  'group': '3.16，通用辅助工具 (Utilities, Optional)',
  'description': '列出当前会话生成的所有 artifacts，便于后续清理或归档。',
  'parameter_raw': 'session_id (string, optional): session_id (str, 可选): 会话 ID，缺省时列出全局 '
                   'artifacts<br>prefix (string, optional): prefix (str, 可选): 用于过滤 artifacts 路径的前缀',
  'returns_raw': 'ok (bool)<br>data (dict): {artifacts}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)<br>projections (dict, 可选)',
  'param_names': ['session_id', 'prefix'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_file', 'rd.capture.open_replay'],
                     'reason': 'This tool operates on a live replay session.'}],
  'namespace': 'util',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'description': 'session_id (str, 可选): 会话 '
                                                                'ID，缺省时列出全局 artifacts',
                                                 'type': 'string'},
                                  'prefix': {'description': 'prefix (str, 可选): 用于过滤 artifacts '
                                                            '路径的前缀',
                                             'type': 'string'}},
                   'required': [],
                   'additionalProperties': False},
  'scope': 'global',
  'effects': [],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.vfs.cat',
  'group': '3.18，VFS 导航工具 (VFS Navigation Tools)',
  'description': '读取 read-only VFS 节点的 JSON 表示，用于路径式浏览与导航；需要精确调试、导出或状态切换时仍应回到 canonical `rd.*` '
                 'tools。',
  'parameter_raw': 'path (string): path (str): VFS 路径<br>session_id (string, optional): session_id '
                   '(str, 可选): 当 path 指向 replay 相关域时用于解析当前 session',
  'returns_raw': 'ok (bool)<br>data (dict): {path, node}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)',
  'param_names': ['path', 'session_id'],
  'prerequisites': [],
  'namespace': 'vfs',
  'input_schema': {'type': 'object',
                   'properties': {'path': {'description': 'path (str): VFS 路径', 'type': 'string'},
                                  'session_id': {'description': 'session_id (str, 可选): 当 path 指向 '
                                                                'replay 相关域时用于解析当前 session',
                                                 'type': 'string'}},
                   'required': ['path'],
                   'additionalProperties': False},
  'scope': 'global',
  'effects': ['replay_position', 'artifact_write'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.vfs.ls',
  'group': '3.18，VFS 导航工具 (VFS Navigation Tools)',
  'description': '以 JSON-first 方式列出 read-only VFS 节点，用于浏览 '
                 'draws/passes/resources/pipeline/context/artifacts 结构；它是导航辅助层，不是第二套调试真相。',
  'parameter_raw': "path (string, optional): path (str, 可选, 默认 '/'): VFS 路径<br>session_id (string, "
                   'optional): session_id (str, 可选): 当 path 指向 replay 相关域时用于解析当前 '
                   'session<br>projection (object, optional): See input_schema for constraints.',
  'returns_raw': 'ok (bool)<br>data (dict): {path, node, entries}<br>projections.tabular (dict, '
                 '可选): {format_version, columns, rows, row_count, tsv_text?} as a tabular summary '
                 'for scan/readability only, not semantic ranking<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)',
  'param_names': ['path', 'session_id', 'projection'],
  'prerequisites': [],
  'supports_projection': {'tabular': True},
  'namespace': 'vfs',
  'input_schema': {'type': 'object',
                   'properties': {'path': {'description': "path (str, 可选, 默认 '/'): VFS 路径",
                                           'type': 'string'},
                                  'session_id': {'description': 'session_id (str, 可选): 当 path 指向 '
                                                                'replay 相关域时用于解析当前 session',
                                                 'type': 'string'},
                                  'projection': {'type': 'object',
                                                 'properties': {'kind': {'type': 'string',
                                                                         'enum': ['tabular']},
                                                                'include_tsv_text': {'type': 'boolean'}},
                                                 'required': ['kind'],
                                                 'additionalProperties': False}},
                   'required': [],
                   'additionalProperties': False},
  'scope': 'global',
  'effects': ['replay_position', 'artifact_write'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.vfs.resolve',
  'group': '3.18，VFS 导航工具 (VFS Navigation Tools)',
  'description': '解析 VFS 路径到对应节点元数据，用于判断 path 是否存在、是否需要 session 以及当前可用的 browse-only 视图，不代替 '
                 'canonical debug/export/state APIs。',
  'parameter_raw': 'path (string): path (str): VFS 路径<br>session_id (string, optional): session_id '
                   '(str, 可选): 当 path 指向 replay 相关域时用于解析当前 session',
  'returns_raw': 'ok (bool)<br>data (dict): {path, node}<br>artifacts (list)<br>error '
                 '(dict|null)<br>meta (dict)',
  'param_names': ['path', 'session_id'],
  'prerequisites': [],
  'namespace': 'vfs',
  'input_schema': {'type': 'object',
                   'properties': {'path': {'description': 'path (str): VFS 路径', 'type': 'string'},
                                  'session_id': {'description': 'session_id (str, 可选): 当 path 指向 '
                                                                'replay 相关域时用于解析当前 session',
                                                 'type': 'string'}},
                   'required': ['path'],
                   'additionalProperties': False},
  'scope': 'global',
  'effects': ['replay_position', 'artifact_write'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.vfs.tree',
  'group': '3.18，VFS 导航工具 (VFS Navigation Tools)',
  'description': '按 VFS 路径返回树形 read-only 视图，适合初步浏览 session 结构或向人展示层级视图；它是 browse-only 辅助层，不代替 '
                 'canonical inspection tools。',
  'parameter_raw': "path (string, optional): path (str, 可选, 默认 '/')<br>session_id (string, "
                   'optional): session_id (str, 可选)<br>depth (integer, optional): depth (int, 可选, '
                   '默认 1)<br>max_nodes (integer, optional): max_nodes (int, 可选, 默认 2000): maximum '
                   'emitted nodes before truncation',
  'returns_raw': 'ok (bool)<br>data (dict): {path, tree, max_nodes, emitted_nodes, truncated, '
                 'truncation_reason}; broad /draws tree nodes defer per-event details with '
                 "detail_deferred=true and recommended_next_tool='rd.event.get_action_details' "
                 'instead of embedding full action subtrees. Broad resource domains are bounded '
                 "and truncated with truncation_reason='max_nodes_exceeded'. Use rd.vfs.ls or "
                 'targeted rd.vfs.cat for large /resources, /textures, and /buffers '
                 'exploration.<br>artifacts (list)<br>error (dict|null)<br>meta (dict)',
  'param_names': ['path', 'session_id', 'depth', 'max_nodes'],
  'prerequisites': [],
  'namespace': 'vfs',
  'input_schema': {'type': 'object',
                   'properties': {'path': {'description': "path (str, 可选, 默认 '/')",
                                           'type': 'string'},
                                  'session_id': {'description': 'session_id (str, 可选)',
                                                 'type': 'string'},
                                  'depth': {'description': 'depth (int, 可选, 默认 1)',
                                            'type': 'integer'},
                                  'max_nodes': {'description': 'max_nodes (int, 可选, 默认 2000): '
                                                               'maximum emitted nodes before '
                                                               'truncation',
                                                'type': 'integer'}},
                   'required': [],
                   'additionalProperties': False},
  'scope': 'global',
  'effects': ['replay_position', 'artifact_write'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.capture.get_thumbnail',
  'group': '3.2，捕获文件与 Replay Session (Capture & Replay)',
  'description': 'Read embedded capture thumbnail without replay.',
  'parameter_raw': 'capture_file_id (string): capture_file_id<br>format (string): '
                   'format<br>max_size (integer): max_size<br>output_path (string): output_path',
  'returns_raw': 'data: capture_file_id, source=embedded_capture_thumbnail, format, byte_size, '
                 'base64 or saved_path. Distinguishes invalid capture, missing thumbnail and read '
                 'failure.',
  'param_names': ['capture_file_id', 'format', 'max_size', 'output_path'],
  'prerequisites': [{'requires': 'capture_file_id',
                     'via_tools': ['rd.capture.open_file'],
                     'reason': 'Requires an owning live handle.'}],
  'namespace': 'capture',
  'input_schema': {'type': 'object',
                   'properties': {'capture_file_id': {'type': 'string', 'minLength': 1},
                                  'format': {'type': 'string',
                                             'enum': ['png', 'jpg'],
                                             'default': 'png'},
                                  'max_size': {'type': 'integer',
                                               'minimum': 1,
                                               'maximum': 2048,
                                               'default': 256},
                                  'output_path': {'type': 'string'}},
                   'required': ['capture_file_id'],
                   'additionalProperties': False},
  'scope': 'capture',
  'effects': ['artifact_write'],
  'evidence_kind': None,
  'path_inputs': [{'name': 'output_path', 'access': 'write'}]},
 {'name': 'rd.event.get_api_calls',
  'group': '3.3，事件导航与 API 检查 (Event Navigation & API Inspection)',
  'description': 'Read captured calls associated with an action or explicit chunk indices.',
  'parameter_raw': 'session_id (string): session_id<br>event_id (integer): '
                   'event_id<br>chunk_indices (array): chunk_indices<br>offset (integer): '
                   'offset<br>limit (integer): limit<br>max_nodes (integer): '
                   'max_nodes<br>object_path (array): child indices within one '
                   'chunk<br>child_offset (integer): resume direct children<br>value_offset '
                   '(integer): resume string characters',
  'returns_raw': 'data: typed calls, total, offset, next_offset, node_budget_exhausted. Exactly '
                 'one event_id/chunk_indices; child and character omissions explicit. Buffers '
                 'referenced without automatic export. Invalid event/chunk and missing structured '
                 'data fail. Each node includes object_path; continue a single chunk using '
                 'next_child_offset or next_value_offset.',
  'param_names': ['session_id',
                  'event_id',
                  'chunk_indices',
                  'offset',
                  'limit',
                  'max_nodes',
                  'object_path',
                  'child_offset',
                  'value_offset'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_replay'],
                     'reason': 'Requires an owning live handle.'}],
  'namespace': 'event',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'type': 'string', 'minLength': 1},
                                  'event_id': {'type': 'integer', 'minimum': 1},
                                  'chunk_indices': {'type': 'array',
                                                    'minItems': 1,
                                                    'maxItems': 1024,
                                                    'items': {'type': 'integer', 'minimum': 0}},
                                  'offset': {'type': 'integer',
                                             'minimum': 0,
                                             'maximum': 2147483647,
                                             'default': 0},
                                  'limit': {'type': 'integer',
                                            'minimum': 1,
                                            'maximum': 200,
                                            'default': 50},
                                  'max_nodes': {'type': 'integer',
                                                'minimum': 1,
                                                'maximum': 16384,
                                                'default': 4096},
                                  'object_path': {'type': 'array',
                                                  'maxItems': 64,
                                                  'items': {'type': 'integer', 'minimum': 0}},
                                  'child_offset': {'type': 'integer', 'minimum': 0, 'default': 0},
                                  'value_offset': {'type': 'integer', 'minimum': 0, 'default': 0}},
                   'required': ['session_id'],
                   'additionalProperties': False,
                   'oneOf': [{'required': ['event_id'], 'not': {'required': ['chunk_indices']}},
                             {'required': ['chunk_indices'], 'not': {'required': ['event_id']}}]},
  'scope': 'replay',
  'effects': [],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.resource.get_descriptors',
  'group': '3.5，资源探查 (Resource Inspection & History)',
  'description': 'Read descriptor-store ranges including entries not accessed by the current '
                 'action.',
  'parameter_raw': 'session_id (string): session_id<br>descriptor_store_id (string): '
                   'descriptor_store_id<br>event_id (integer): event_id<br>first (integer): '
                   'first<br>count (integer): count<br>type (string): type',
  'returns_raw': 'data: descriptor_store_id, resolved_event_id, indexed descriptors and logical '
                 'locations, total, next_first. Empty slots retained; invalid ranges and '
                 'incomplete reads fail.',
  'param_names': ['session_id', 'descriptor_store_id', 'event_id', 'first', 'count', 'type'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_replay'],
                     'reason': 'Requires an owning live handle.'}],
  'namespace': 'resource',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'type': 'string', 'minLength': 1},
                                  'descriptor_store_id': {'type': 'string', 'minLength': 1},
                                  'event_id': {'type': 'integer', 'minimum': 1},
                                  'first': {'type': 'integer',
                                            'minimum': 0,
                                            'maximum': 2147483647,
                                            'default': 0},
                                  'count': {'type': 'integer',
                                            'minimum': 1,
                                            'maximum': 1024,
                                            'default': 64},
                                  'type': {'type': 'string',
                                           'enum': ['resource', 'sampler'],
                                           'default': 'resource'}},
                   'required': ['session_id', 'descriptor_store_id'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position'],
  'evidence_kind': None,
  'path_inputs': []},
 {'name': 'rd.perf.get_frame_timing',
  'group': '3.10，性能计数器与测量 (Performance Counters)',
  'description': 'Measure the full single-queue replay with native GPU timestamps, restoring the '
                 'original event.',
  'parameter_raw': 'session_id (string): owning replay<br>samples (integer): retained samples, '
                   '1..16<br>warmup (integer): discarded warmup replays, 0..4',
  'returns_raw': 'data: frame_timing method, unit, range, scope, sampling conditions and '
                 'individual positive samples; restored_event_id and replay_state_restored. '
                 'Excludes initial-content restoration, includes replay scheduling gaps, never '
                 'original application time. Unsupported backend, incomplete queues and failed '
                 'timestamps are errors, not zero samples.',
  'param_names': ['session_id', 'samples', 'warmup'],
  'prerequisites': [{'requires': 'session_id',
                     'via_tools': ['rd.capture.open_replay'],
                     'reason': 'Requires an owning live replay.'}],
  'namespace': 'perf',
  'input_schema': {'type': 'object',
                   'properties': {'session_id': {'type': 'string', 'minLength': 1},
                                  'samples': {'type': 'integer',
                                              'minimum': 1,
                                              'maximum': 16,
                                              'default': 3},
                                  'warmup': {'type': 'integer',
                                             'minimum': 0,
                                             'maximum': 4,
                                             'default': 1}},
                   'required': ['session_id'],
                   'additionalProperties': False},
  'scope': 'replay',
  'effects': ['replay_position_temporary'],
  'evidence_kind': 'measurement',
  'path_inputs': []}]
