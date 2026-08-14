-- Fill blank radical-lookup comments from a separate audited supplement.
-- If neither kMandarin17 nor the supplement has a reading, display n/a.
-- This is display-only: candidates and both source dictionaries stay intact.

local M = {}

local function is_blank(value)
    return value == nil or value:match("^%s*$") ~= nil
end

function M.init(env)
    local ok, reverse_lookup = pcall(function()
        return ReverseLookup("radical_reading_supplement")
    end)
    if ok then
        env.supplement_reverse_lookup = reverse_lookup
    end
end

local function supplement_comment(env, text)
    if env.supplement_reverse_lookup == nil then
        return nil
    end
    local ok, value = pcall(function()
        return env.supplement_reverse_lookup:lookup(text)
    end)
    if not ok or is_blank(value) then
        return nil
    end
    return value:match("^%s*(.-)%s*$")
end

function M.func(input, env)
    local raw_input = env.engine.context.input
    local is_radical_lookup = raw_input:match("^uU[a-z]+$") ~= nil

    for cand in input:iter() do
        if is_radical_lookup and is_blank(cand.comment) then
            local comment = supplement_comment(env, cand.text) or "n/a"
            yield(cand:to_shadow_candidate(cand.type, cand.text, comment))
        else
            yield(cand)
        end
    end
end

return M
