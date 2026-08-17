-- Keep kaomoji out of ordinary pinyin menus without deleting existing user
-- dictionary entries. The dedicated kmj-prefixed segment remains unchanged.

local M = {}

local function load_kaomoji_texts()
    local dictionary_path = rime_api.get_user_data_dir() .. "/cn_dicts/kaomoji.dict.yaml"
    local file = io.open(dictionary_path, "rb")
    if not file then
        log.error("[kaomoji_isolation] dictionary is missing: " .. dictionary_path)
        return {}
    end

    local texts = {}
    for line in file:lines() do
        if not line:match("^%s*#") then
            local text = line:match("^([^\t]+)\t")
            if text and text ~= "" then
                texts[text] = true
            end
        end
    end
    file:close()
    return texts
end

function M.init(env)
    env.kaomoji_texts = load_kaomoji_texts()
end

function M.func(input, env)
    local raw_input = env.engine.context.input or ""
    local dedicated_kaomoji_input = raw_input:match("^kmj[A-Za-z]+$") ~= nil

    for candidate in input:iter() do
        if dedicated_kaomoji_input or not env.kaomoji_texts[candidate.text] then
            yield(candidate)
        end
    end
end

return M
