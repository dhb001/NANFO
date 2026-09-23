"""Atomic bounded retention primitives. No trimming or consumer-state mutation."""

# IDs are uint64 pairs: Lua doubles must not be used to compare them.
COMMON = r"""
local function less(a, b)
    local am, as = string.match(a, '^(%d+)%-(%d+)$')
    local bm, bs = string.match(b, '^(%d+)%-(%d+)$')
    if not am or not bm then error('retention_invalid_id') end
    if #am ~= #bm then return #am < #bm end
    if am ~= bm then return am < bm end
    if #as ~= #bs then return #as < #bs end
    return as < bs
end
local function map(values)
    local result = {}
    for i = 1, #values, 2 do result[values[i]] = values[i+1] end
    return result
end
local function state(key, expected)
    local info = map(redis.call('XINFO', 'STREAM', key))
    if not info.groups or info.groups < 1 or info.groups > 64 then
        error('retention_group_count')
    end
    local groups = redis.call('XINFO', 'GROUPS', key)
    if #groups ~= #expected then error('retention_unknown_groups') end
    table.sort(groups, function(a,b) return map(a).name < map(b).name end)
    local result = {}
    for i, raw in ipairs(groups) do
        local g = map(raw)
        if g.name ~= expected[i] then error('retention_unknown_groups') end
        if type(g['entries-read']) ~= 'number' or g['entries-read'] < 0
            or type(g.lag) ~= 'number' or g.lag < 0
            or type(g.pending) ~= 'number' or g.pending < 0
            or type(g.consumers) ~= 'number' or g.consumers < 0 or g.consumers > 64
            or type(g['last-delivered-id']) ~= 'string' then
            error('retention_unknown_state')
        end
        local p = redis.call('XPENDING', key, g.name)
        if p[1] ~= g.pending then error('retention_unknown_pending') end
        local first = p[2] or ''
        if g.pending > 0 and first == '' then error('retention_unknown_pending') end
        -- Lag is checked, but not included: concurrent appends must not stall GC.
        result[i] = {g.name, g['last-delivered-id'], g['entries-read'],
                     g.pending, first, g.consumers}
    end
    return result
end
local function eligible(id, cutoff, groups)
    if not less(id, cutoff) then return false end
    for _, g in ipairs(groups) do
        if less(g[2], id) or (g[5] ~= '' and not less(id, g[5])) then return false end
    end
    return true
end
"""

PLAN = COMMON + r"""
local groups = state(KEYS[1], cjson.decode(ARGV[1]))
local selected = {}
local total = 0
local cursor = ARGV[2]
local count = tonumber(ARGV[4])
if not count or count < 1 or count > 100 then error('retention_invalid_count') end
for i = 1, count do
    -- Read one at a time: an oversized existing entry must not expand a full page.
    local page = redis.call('XRANGE', KEYS[1], cursor, '(' .. ARGV[3], 'COUNT', 1)
    if #page == 0 then break end
    local entry = page[1]
    if not eligible(entry[1], ARGV[3], groups) then break end
    local size = #entry[1]
    for _, value in ipairs(entry[2]) do size = size + #value end
    if size > 65536 or #entry[2] > 256 then error('retention_entry_too_large') end
    total = total + size
    if total > 1048576 then break end
    selected[#selected+1] = entry
    cursor = '(' .. entry[1]
end
return {cmsgpack.pack(groups), selected, groups}
"""

DELETE = COMMON + r"""
local groups = state(KEYS[1], cjson.decode(ARGV[1]))
if cmsgpack.pack(groups) ~= ARGV[2] then error('retention_state_changed') end
local count = tonumber(ARGV[4])
if not count or count < 1 or count > 100 then error('retention_invalid_count') end
local ids = {}
local offset = 5
for i = 1, count do
    local id = ARGV[offset]
    local fields = tonumber(ARGV[offset+1])
    if not fields or fields < 2 or fields % 2 ~= 0 then error('retention_invalid_fields') end
    if not eligible(id, ARGV[3], groups) then error('retention_boundary_changed') end
    local current = redis.call('XRANGE', KEYS[1], id, id, 'COUNT', 1)
    if #current ~= 1 or #current[1][2] ~= fields then error('retention_entry_changed') end
    for j = 1, fields do
        if current[1][2][j] ~= ARGV[offset+1+j] then error('retention_entry_changed') end
    end
    ids[i] = id
    offset = offset + fields + 2
end
if offset ~= #ARGV+1 then error('retention_invalid_arguments') end
return redis.call('XDEL', KEYS[1], unpack(ids))
"""

RESTORE = COMMON + r"""
local count = tonumber(ARGV[1])
if not count or count < 1 or count > 100 then error('retention_invalid_count') end
local last = '0-0'
if redis.call('EXISTS', KEYS[1]) == 1 then
    local info = map(redis.call('XINFO', 'STREAM', KEYS[1]))
    if info.groups ~= 0 then error('retention_recovery_has_groups') end
    last = info['last-generated-id']
end
local offset = 2
local missing = {}
for i = 1, count do
    local id = ARGV[offset]
    local fields = tonumber(ARGV[offset+1])
    if not fields or fields < 2 or fields % 2 ~= 0 then error('retention_invalid_fields') end
    local values = {}
    for j = 1, fields do values[j] = ARGV[offset+1+j] end
    local current = redis.call('XRANGE', KEYS[1], id, id, 'COUNT', 1)
    if #current == 1 then
        if #current[1][2] ~= fields then error('retention_recovery_conflict') end
        for j = 1, fields do
            if current[1][2][j] ~= values[j] then error('retention_recovery_conflict') end
        end
    else
        if not less(last, id) then error('retention_recovery_order') end
        last = id
        missing[#missing+1] = {id, values}
    end
    offset = offset + fields + 2
end
if offset ~= #ARGV+1 then error('retention_invalid_arguments') end
for _, entry in ipairs(missing) do
    redis.call('XADD', KEYS[1], entry[1], unpack(entry[2]))
end
return #missing
"""
