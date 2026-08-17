-- Asynchronous cloud pinyin shared by macOS Rime frontends.
--
-- Network requests run in cloud_pinyin_async_helper, outside the Rime frontend.
-- Lua only exchanges small state files and rebuilds the candidate menu after a
-- private F24 event delivered directly to the active Rime engine by the
-- frontend-specific refresh bridge. Selected cloud candidates are explicitly
-- written to the active schema's user dictionary.

local M = {}

local REQUEST_PROPERTY = "cloud_pinyin_async_request"
local READY_PROPERTY = "cloud_pinyin_async_ready"
local REFILL_PROPERTY = "cloud_pinyin_async_refill"
local REFILL_MARKER = "-refill-"
local REQUEST_FILE = "cloud_pinyin_async.request"
local RESPONSE_FILE = "cloud_pinyin_async.response"
local HEARTBEAT_FILE = "cloud_pinyin_async.heartbeat"
local HELPER_FILE = "cloud_pinyin_async_helper"
local LOCAL_DUPLICATE_SCAN_LIMIT = 50
local RESPONSE_MAGIC = "RIME_CLOUD_V1"

local user_dir = rime_api.get_user_data_dir()
local response_history = {}
local response_order = {}
local cached_response_text = nil
local cached_response = nil
local last_helper_launch = 0
local recent_cloud_codes = {}
local recent_cloud_order = {}

local tone_map = {
    ["ā"] = "a", ["á"] = "a", ["ǎ"] = "a", ["à"] = "a",
    ["ē"] = "e", ["é"] = "e", ["ě"] = "e", ["è"] = "e",
    ["ī"] = "i", ["í"] = "i", ["ǐ"] = "i", ["ì"] = "i",
    ["ō"] = "o", ["ó"] = "o", ["ǒ"] = "o", ["ò"] = "o",
    ["ū"] = "u", ["ú"] = "u", ["ǔ"] = "u", ["ù"] = "u",
    ["ǖ"] = "v", ["ǘ"] = "v", ["ǚ"] = "v", ["ǜ"] = "v", ["ü"] = "v",
    ["ń"] = "n", ["ň"] = "n", ["ǹ"] = "n",
}

local function path(name)
    return user_dir .. "/" .. name
end

local function read_all(file_path)
    local file = io.open(file_path, "rb")
    if not file then
        return nil
    end
    local value = file:read("*a")
    file:close()
    return value
end

local function split_tab(line)
    local fields = {}
    for field in (line .. "\t"):gmatch("(.-)\t") do
        fields[#fields + 1] = field
    end
    return fields
end

local base64_alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
local base64_values = {}
for index = 1, #base64_alphabet do
    base64_values[base64_alphabet:sub(index, index)] = index - 1
end

local function base64_decode(value)
    local output = {}
    local accumulator = 0
    local bits = 0
    for index = 1, #value do
        local char = value:sub(index, index)
        if char == "=" then
            break
        end
        local digit = base64_values[char]
        if digit then
            accumulator = accumulator * 64 + digit
            bits = bits + 6
            if bits >= 8 then
                bits = bits - 8
                local divisor = 2 ^ bits
                local byte = math.floor(accumulator / divisor) % 256
                output[#output + 1] = string.char(byte)
                accumulator = accumulator % divisor
            end
        end
    end
    return table.concat(output)
end

local function response_token(response)
    return response.id .. ":" .. tostring(response.revision)
end

local function remember_response(response)
    local token = response_token(response)
    if not response_history[token] then
        response_order[#response_order + 1] = token
    end
    response_history[token] = response
    while #response_order > 8 do
        local expired = table.remove(response_order, 1)
        response_history[expired] = nil
    end
    return token
end

local function parse_response(text)
    if not text or text == "" then
        return nil
    end

    local lines = {}
    for line in text:gmatch("[^\r\n]+") do
        lines[#lines + 1] = line
    end
    if #lines == 0 then
        return nil
    end

    local header = split_tab(lines[1])
    if header[1] ~= RESPONSE_MAGIC or #header < 9 then
        return nil
    end

    local response = {
        id = header[2],
        input = header[3],
        query = header[4],
        revision = tonumber(header[5]) or 0,
        sogou_ms = tonumber(header[6]) or -1,
        google_ms = tonumber(header[7]) or -1,
        sogou_status = header[8],
        google_status = header[9],
        candidates = {},
    }

    for index = 2, #lines do
        local fields = split_tab(lines[index])
        if fields[1] == "C" and #fields >= 4 then
            local text_value = base64_decode(fields[2])
            if text_value ~= "" then
                response.candidates[#response.candidates + 1] = {
                    text = text_value,
                    pinyin = base64_decode(fields[3]),
                    sources = fields[4],
                }
            end
        end
    end

    if #response.candidates == 0 then
        return nil
    end
    return response
end

local function read_current_response()
    local text = read_all(path(RESPONSE_FILE))
    if text == cached_response_text then
        return cached_response
    end

    cached_response_text = text
    local ok, response = pcall(parse_response, text)
    if not ok then
        log.error("[cloud_pinyin_async] invalid response: " .. tostring(response))
        cached_response = nil
        return nil
    end

    cached_response = response
    if response then
        remember_response(response)
    end
    return response
end

local function active_response(context)
    local token = context:get_property(READY_PROPERTY)
    if not token or token == "" then
        return nil
    end
    local response = response_history[token]
    if response then
        return response
    end
    response = read_current_response()
    if response and response_token(response) == token then
        return response
    end
    return nil
end

local function config_number(config, key, default_value)
    local value = config:get_int("cloud_pinyin_async/" .. key)
    return tonumber(value) or default_value
end

local function load_config(env)
    local config = env.engine.schema.config
    return {
        delay_ms = config_number(config, "delay_ms", 500),
        timeout_ms = config_number(config, "timeout_ms", 900),
        candidates_per_source = config_number(config, "candidates_per_source", 5),
        max_candidates = config_number(config, "max_candidates", 8),
        insert_after = config_number(config, "insert_after", 3),
        min_input_length = config_number(config, "min_input_length", 2),
        learn_to_user_dict = config:get_bool("cloud_pinyin_async/learn_to_user_dict") ~= false,
        refill_on_duplicate = config:get_bool("cloud_pinyin_async/refill_on_duplicate") ~= false,
        refill_delay_ms = config_number(config, "refill_delay_ms", 100),
        refill_candidates_per_source = config_number(config, "refill_candidates_per_source", 10),
        refill_max_candidates = config_number(config, "refill_max_candidates", 20),
    }
end

local function helper_is_alive()
    local heartbeat = tonumber(read_all(path(HEARTBEAT_FILE)) or "")
    return heartbeat and math.abs(os.time() - heartbeat) <= 6
end

local function shell_quote(value)
    return "'" .. value:gsub("'", "'\"'\"'") .. "'"
end

local function ensure_helper()
    if helper_is_alive() then
        return true
    end

    local now = os.time()
    if now - last_helper_launch < 5 then
        return false
    end
    last_helper_launch = now

    local helper_path = path(HELPER_FILE)
    local probe = io.open(helper_path, "rb")
    if not probe then
        log.error("[cloud_pinyin_async] helper is missing: " .. helper_path)
        return false
    end
    probe:close()

    local command = "/usr/bin/nohup " .. shell_quote(helper_path) ..
        " " .. shell_quote(user_dir) .. " >/dev/null 2>&1 &"
    os.execute(command)
    return true
end

local function write_request(request_id, context_input, query_input, config, overrides)
    -- Never launch a process from an input/update callback. The processor init
    -- performs the single best-effort startup; if the helper later disappears,
    -- local input keeps working and the next engine initialization retries.
    overrides = overrides or {}
    local file = io.open(path(REQUEST_FILE), "wb")
    if not file then
        log.error("[cloud_pinyin_async] cannot write request file")
        return false
    end
    file:write(
        request_id, "\t",
        context_input, "\t",
        query_input, "\t",
        tostring(overrides.delay_ms or config.delay_ms), "\t",
        tostring(config.timeout_ms), "\t",
        tostring(overrides.candidates_per_source or config.candidates_per_source), "\t",
        tostring(overrides.max_candidates or config.max_candidates), "\n")
    file:close()
    return true
end

local function current_segment(context)
    local composition = context.composition
    if not composition or composition:empty() then
        return nil
    end
    return composition:back()
end

local function current_request_target(context, config, allow_menu_rebuild)
    local context_input = context.input or ""
    -- A filter runs while Rime is rebuilding the candidate menu, when
    -- Context.has_menu() is temporarily false even though composition and the
    -- active abc segment are valid. Scheduling still requires an existing
    -- menu; response validation inside the filter may opt into this state.
    if not allow_menu_rebuild and not context:has_menu() then
        return nil
    end

    local segment = current_segment(context)
    if not segment or not segment.tags or not segment.tags["abc"] then
        return nil
    end

    -- Confirming a candidate advances the active segment but deliberately
    -- keeps Context.input unchanged. Query only that unconfirmed suffix while
    -- retaining the full input as the stale-response guard.
    local segment_input = context_input:sub(segment.start + 1, segment._end)
    if #segment_input < config.min_input_length or
        not segment_input:match("^[a-z']+$") then
        return nil
    end

    local query_input = segment_input:gsub("'", "")
    local target_key = table.concat({
        context_input,
        tostring(segment.start),
        tostring(segment._end),
        query_input,
    }, "\31")
    return {
        context_input = context_input,
        segment_input = segment_input,
        query_input = query_input,
        start = segment.start,
        finish = segment._end,
        key = target_key,
        signature = target_key .. "\31" .. tostring(context.caret_pos),
    }
end

local function response_matches_target(context, response, config, allow_menu_rebuild)
    if not response or
        response.id ~= context:get_property(REQUEST_PROPERTY) then
        return nil
    end

    local target = current_request_target(context, config, allow_menu_rebuild)
    if not target or
        response.input ~= target.context_input or
        response.query ~= target.query_input then
        return nil
    end
    return target
end

local function make_nonce(env)
    local raw = tostring(env.engine) .. "-" .. tostring(os.time()) .. "-" .. tostring(math.floor(os.clock() * 1000000))
    return raw:gsub("[^%w%-]", "")
end

local function schedule_context(context, env)
    local input = context.input or ""
    local target = current_request_target(context, env.cloud_config)
    local signature = target and target.signature or
        table.concat({ input, tostring(context.caret_pos), "inactive" }, "\31")

    -- Rebuilding the menu after a cloud response can itself emit update
    -- notifications (and may change caret metadata). Keep the accepted request
    -- stable until the user actually changes the input, so a second provider
    -- can merge into the same candidate menu instead of becoming stale.
    if env.active_cloud_target then
        if target and target.key == env.active_cloud_target and
            context:get_property(READY_PROPERTY) ~= "" then
            env.last_signature = signature
            return
        end
        env.active_cloud_target = nil
    end

    if signature == env.last_signature then
        return
    end
    env.last_signature = signature
    env.sequence = env.sequence + 1

    local request_id = env.nonce .. "-" .. tostring(env.sequence)
    context:set_property(REQUEST_PROPERTY, request_id)
    context:set_property(READY_PROPERTY, "")
    context:set_property(REFILL_PROPERTY, "")

    if target then
        write_request(
            request_id,
            target.context_input,
            target.query_input,
            env.cloud_config)
    else
        write_request(request_id, "", "", env.cloud_config)
        if input == "" then
            env.pending_cloud = {}
        end
    end
end

local function normalize_code(code)
    if not code then
        return nil
    end
    code = code:lower():gsub("'", " "):gsub("[^a-zv%s]", " ")
    code = code:gsub("%s+", " "):gsub("^%s+", ""):gsub("%s+$", "")
    if code == "" then
        return nil
    end
    return code
end

local function remove_tone(value)
    local output = {}
    for char in value:gmatch("[%z\1-\127\194-\244][\128-\191]*") do
        output[#output + 1] = tone_map[char] or char
    end
    return table.concat(output):lower():gsub("[^a-zv]", "")
end

local function comment_to_code(comment)
    local syllables = {}
    for chunk in (comment or ""):gmatch("%S+") do
        local head = chunk:match("^([^;]+)") or ""
        local syllable = remove_tone(head)
        if syllable ~= "" then
            syllables[#syllables + 1] = syllable
        end
    end
    if #syllables == 0 then
        return nil
    end
    return table.concat(syllables, " ")
end

local function derive_local_code(input, segment, env)
    local code = nil
    if env.main_translator then
        local ok, translation = pcall(function()
            return env.main_translator:query(input, segment)
        end)
        if ok and translation then
            local seen = 0
            for candidate in translation:iter() do
                seen = seen + 1
                if candidate._end - candidate.start >= segment._end - segment.start then
                    code = comment_to_code(candidate.comment or "")
                    if code then
                        break
                    end
                end
                if seen >= 8 then
                    break
                end
            end
        end
    end

    if not code and input:find("'", 1, true) then
        code = normalize_code(input)
    end
    return code
end

local function source_comment(sources)
    if sources == "SG+GG" then
        return " ☁搜谷"
    elseif sources == "SG" then
        return " ☁搜"
    end
    return " ☁谷"
end

local function genuine_candidate(candidate)
    local ok, genuine = pcall(function()
        return candidate:get_genuine()
    end)
    if ok and genuine then
        return genuine
    end
    return candidate
end

local function preferred_local_variant(candidate)
    local preferred = nil
    local fallback = nil
    local contains_cloud = false
    local ok, variants = pcall(function()
        return candidate:get_genuines()
    end)
    if ok and variants then
        for _, variant in ipairs(variants) do
            local genuine = genuine_candidate(variant)
            if genuine.type == "cloud_pinyin_async" then
                contains_cloud = true
            elseif variant.type == "user_phrase" or genuine.type == "user_phrase" then
                preferred = preferred or variant
            else
                fallback = fallback or variant
            end
        end
    end

    local genuine = genuine_candidate(candidate)
    if genuine.type == "cloud_pinyin_async" then
        contains_cloud = true
    elseif candidate.type == "user_phrase" or genuine.type == "user_phrase" then
        preferred = preferred or candidate
    else
        fallback = fallback or candidate
    end
    return preferred or fallback, contains_cloud
end

local function response_suppresses_text(response, text)
    return response and
        response.suppressed_texts and
        response.suppressed_texts[text] == true
end

local function providers_finished(response)
    return response and
        response.sogou_status ~= "pending" and
        response.google_status ~= "pending"
end

local function request_duplicate_refill(context, response, config)
    if not config.refill_on_duplicate or
        not providers_finished(response) or
        response.id:find(REFILL_MARKER, 1, true) or
        not response_matches_target(context, response, config, true) then
        return false
    end

    local refill_token = response_token(response)
    if context:get_property(REFILL_PROPERTY) == refill_token then
        return false
    end

    local candidates_per_source = math.min(
        10,
        math.max(config.candidates_per_source + 1, config.refill_candidates_per_source))
    local max_candidates = math.min(
        20,
        math.max(config.max_candidates + 1, config.refill_max_candidates))
    if candidates_per_source <= config.candidates_per_source and
        max_candidates <= config.max_candidates then
        return false
    end

    local request_id = response.id .. REFILL_MARKER .. tostring(response.revision)
    local written = write_request(
        request_id,
        response.input,
        response.query,
        config,
        {
            delay_ms = config.refill_delay_ms,
            candidates_per_source = candidates_per_source,
            max_candidates = max_candidates,
        })
    if not written then
        return false
    end

    context:set_property(REFILL_PROPERTY, refill_token)
    context:set_property(REQUEST_PROPERTY, request_id)
    context:set_property(READY_PROPERTY, "")
    log.info(
        "[cloud_pinyin_async] duplicate refill requested: per_source=" ..
        tostring(candidates_per_source) ..
        " pool=" .. tostring(max_candidates))
    return true
end

local function remember_cloud_code(text, code, token, input)
    if not text or not code then
        return
    end
    if not recent_cloud_codes[text] then
        recent_cloud_order[#recent_cloud_order + 1] = text
    end
    recent_cloud_codes[text] = {
        code = code,
        token = token,
        input = input,
    }
    while #recent_cloud_order > 64 do
        local expired = table.remove(recent_cloud_order, 1)
        recent_cloud_codes[expired] = nil
    end
end

local function learn_pending(context, env)
    local pending = env.pending_cloud
    env.pending_cloud = {}
    local activated_response = env.last_activated_response
    env.last_activated_response = nil
    if not env.cloud_config.learn_to_user_dict or not env.memory then
        return
    end

    local commit_text = context:get_commit_text() or ""
    local selected = {}
    for _, item in ipairs(pending or {}) do
        if commit_text:find(item.text, 1, true) and not selected[item.text .. "\31" .. item.code] then
            selected[item.text .. "\31" .. item.code] = item
        end
    end

    -- Direct selection with Space/number keys does not reliably emit
    -- select_notifier on Weasel. Match the actual committed text against the
    -- last response that was rendered, which covers keyboard and mouse commits
    -- without depending on the wrapped candidate type.
    if activated_response then
        for _, candidate in ipairs(activated_response.candidates or {}) do
            if not response_suppresses_text(activated_response, candidate.text) and
                commit_text:find(candidate.text, 1, true) then
                local remembered = recent_cloud_codes[candidate.text]
                local code = activated_response.learn_codes and activated_response.learn_codes[candidate.text] or nil
                code = code or (remembered and remembered.code or nil)
                code = code or normalize_code(candidate.pinyin)
                if code then
                    selected[candidate.text .. "\31" .. code] = {
                        text = candidate.text,
                        code = code,
                    }
                    log.info("[cloud_pinyin_async] matched committed cloud candidate")
                end
            end
        end
    end
    if not next(selected) then
        return
    end

    local started = false
    if env.memory.start_session then
        env.memory:start_session()
        started = true
    end

    for _, item in pairs(selected) do
        local entry = DictEntry()
        entry.text = item.text
        entry.custom_code = item.code .. " "
        local ok, updated = pcall(function()
            return env.memory:update_userdict(entry, 1, "")
        end)
        if not ok or not updated then
            log.error("[cloud_pinyin_async] failed to learn cloud candidate")
        else
            log.info("[cloud_pinyin_async] learned cloud candidate")
        end
    end

    if started and env.memory.finish_session then
        env.memory:finish_session()
    end
end

local function capture_cloud_selection(current, env)
    local candidate = current:get_selected_candidate()
    if not candidate then
        return
    end

    local genuine = genuine_candidate(candidate)
    local candidate_text = candidate.text or genuine.text or ""
    local marked_cloud = (candidate.comment or ""):find("☁", 1, true) ~= nil
    local response = active_response(current)
    local response_item = nil
    if response then
        for _, item in ipairs(response.candidates) do
            if item.text == candidate_text then
                response_item = item
                break
            end
        end
    end

    if response_suppresses_text(response, candidate_text) and
        genuine.type ~= "cloud_pinyin_async" and
        not marked_cloud then
        return
    end

    if genuine.type ~= "cloud_pinyin_async" and not marked_cloud and not response_item then
        return
    end

    local remembered = recent_cloud_codes[candidate_text]
    local code = remembered and remembered.code or nil
    if not code and response and response.learn_codes then
        code = response.learn_codes[candidate_text]
    end
    if not code and response_item then
        code = normalize_code(response_item.pinyin)
    end
    code = code or normalize_code(genuine.preedit or candidate.preedit or "")
    if not code then
        log.error("[cloud_pinyin_async] selected cloud candidate has no learnable code")
        return
    end

    env.pending_cloud[#env.pending_cloud + 1] = {
        text = candidate_text,
        code = code,
    }
    log.info("[cloud_pinyin_async] captured cloud selection")
end

local function processor_init(env)
    env.cloud_config = load_config(env)
    env.last_signature = nil
    env.sequence = 0
    env.nonce = make_nonce(env)
    env.pending_cloud = {}
    env.active_cloud_target = nil
    env.last_activated_response = nil

    local ok, memory = pcall(function()
        return Memory(env.engine, env.engine.schema)
    end)
    if ok then
        env.memory = memory
    else
        env.memory = nil
        log.error("[cloud_pinyin_async] cannot open schema user dictionary: " .. tostring(memory))
    end

    local context = env.engine.context
    env.update_connection = context.update_notifier:connect(function(current)
        schedule_context(current, env)
    end)
    env.select_connection = context.select_notifier:connect(function(current)
        capture_cloud_selection(current, env)
        -- Partial selection does not necessarily emit update_notifier. The
        -- select callback runs after Rime advances composition, so explicitly
        -- schedule the newly active suffix here.
        schedule_context(current, env)
    end)
    env.commit_connection = context.commit_notifier:connect(function(current)
        learn_pending(current, env)
    end)

    ensure_helper()
    schedule_context(context, env)
end

local function processor_fini(env)
    if env.update_connection then
        env.update_connection:disconnect()
    end
    if env.select_connection then
        env.select_connection:disconnect()
    end
    if env.commit_connection then
        env.commit_connection:disconnect()
    end
    if env.memory and env.memory.disconnect then
        env.memory:disconnect()
    end
end

local function processor_func(key, env)
    local representation = key:repr()
    if representation ~= "F24" and representation ~= "Release+F24" then
        return 2
    end
    if representation == "Release+F24" then
        return 1
    end

    local context = env.engine.context
    local response = read_current_response()
    local target = response_matches_target(context, response, env.cloud_config)
    if not target then
        log.info("[cloud_pinyin_async] refresh ignored: stale response")
        return 1
    end
    if not context:is_composing() or not context:has_menu() then
        log.info("[cloud_pinyin_async] refresh ignored: no active menu")
        return 1
    end

    local segment = current_segment(context)
    if not segment or segment.selected_index ~= 0 then
        log.info("[cloud_pinyin_async] refresh ignored: selection moved")
        return 1
    end

    env.active_cloud_target = target.key
    env.last_activated_response = response
    context:set_property(READY_PROPERTY, response_token(response))
    log.info("[cloud_pinyin_async] activating response " .. response_token(response))
    context:refresh_non_confirmed_composition()
    return 1
end

M.processor = {
    init = processor_init,
    func = processor_func,
    fini = processor_fini,
}

local function translator_init(env)
    env.cloud_config = load_config(env)
    local ok, translator = pcall(function()
        return Component.Translator(env.engine, "translator", "script_translator")
    end)
    if ok then
        env.main_translator = translator
    end
    env.code_cache_token = nil
    env.code_cache_value = nil
    env.last_logged_response = nil
end

local function translator_func(input, segment, env)
    local context = env.engine.context
    local response = active_response(context)
    local query_input = (input or ""):gsub("'", "")
    if not response or
        response.id ~= context:get_property(REQUEST_PROPERTY) or
        response.input ~= (context.input or "") or
        response.query ~= query_input then
        return
    end

    local token = response_token(response)
    if env.last_logged_response ~= token then
        env.last_logged_response = token
        log.info(
            "[cloud_pinyin_async] yielding " ..
            tostring(#response.candidates) ..
            " cloud candidates from " .. token)
    end
    if env.code_cache_token ~= token then
        env.code_cache_token = token
        env.code_cache_value = derive_local_code(input, segment, env)
    end
    response.learn_codes = response.learn_codes or {}

    for _, item in ipairs(response.candidates) do
        local code = normalize_code(item.pinyin)
        if item.sources == "SG" and env.code_cache_value then
            code = env.code_cache_value
        end
        code = code or normalize_code(input)
        if code then
            response.learn_codes[item.text] = code
            remember_cloud_code(item.text, code, token, input)
        end

        local candidate = Candidate(
            "cloud_pinyin_async",
            segment.start,
            segment._end,
            item.text,
            source_comment(item.sources))
        candidate.quality = 10000
        if code then
            candidate.preedit = code
        end
        yield(candidate)
    end
end

M.translator = {
    init = translator_init,
    func = translator_func,
}

local function filter_init(env)
    env.cloud_config = load_config(env)
end

local function filter_func(input, env)
    local context = env.engine.context
    local response = active_response(context)
    if not response_matches_target(context, response, env.cloud_config, true) then
        for candidate in input:iter() do
            yield(candidate)
        end
        return
    end

    response.suppressed_texts = response.suppressed_texts or {}
    -- This filter must run before order-changing filters such as
    -- long_word_filter. Cloud candidates carry a deliberately high quality,
    -- so letting those filters see the cloud stream first changes their
    -- baseline and can move words such as "西安" ahead of the native local
    -- leaders "先、线".
    --
    -- Buffer a small local window before yielding anything. Besides preserving
    -- the native local head, the window lets us suppress same-text cloud items
    -- without relying on uniquifier's lazy, already-yielded candidate wrappers.
    local cloud_candidates = {}
    local local_candidates = {}
    local local_texts = {}
    local cloud_count = 0
    local refill_requested = false
    local seen_text = {}

    local function candidate_text(candidate)
        local genuine = genuine_candidate(candidate)
        return candidate.text or genuine.text or ""
    end

    local function suppress_cloud_text(text)
        if text == "" then
            return
        end
        response.suppressed_texts[text] = true
        if not refill_requested then
            refill_requested = request_duplicate_refill(
                context,
                response,
                env.cloud_config)
        end
    end

    local function remember_local(candidate, contains_cloud)
        local text = candidate_text(candidate)
        if text == "" or not local_texts[text] then
            local_candidates[#local_candidates + 1] = candidate
            if text ~= "" then
                local_texts[text] = true
            end
        end
        if contains_cloud then
            suppress_cloud_text(text)
        end
    end

    local scan_limit = math.max(
        LOCAL_DUPLICATE_SCAN_LIMIT,
        math.max(0, env.cloud_config.insert_after))
    for candidate in input:iter() do
        local local_variant, contains_cloud = preferred_local_variant(candidate)
        if contains_cloud and local_variant then
            remember_local(local_variant, true)
        elseif contains_cloud then
            cloud_candidates[#cloud_candidates + 1] = candidate
        else
            remember_local(candidate, false)
        end
        if #local_candidates >= scan_limit then
            break
        end
    end

    local function emit(candidate)
        local text = candidate_text(candidate)
        if text ~= "" and seen_text[text] then
            return false
        end
        yield(candidate)
        if text ~= "" then
            seen_text[text] = true
        end
        return true
    end

    local local_head_count = math.min(
        #local_candidates,
        math.max(0, env.cloud_config.insert_after))
    for index = 1, local_head_count do
        emit(local_candidates[index])
    end

    for _, candidate in ipairs(cloud_candidates) do
        if cloud_count >= env.cloud_config.max_candidates then
            break
        end
        local text = candidate_text(candidate)
        if text ~= "" and local_texts[text] then
            suppress_cloud_text(text)
        elseif emit(candidate) then
            cloud_count = cloud_count + 1
        end
    end

    for index = local_head_count + 1, #local_candidates do
        emit(local_candidates[index])
    end

    -- The high cloud quality normally puts every cloud item inside the scan
    -- window. Still handle a late item defensively for schemas with additional
    -- translators or custom quality rules.
    for candidate in input:iter() do
        local local_variant, contains_cloud = preferred_local_variant(candidate)
        if contains_cloud and local_variant then
            local text = candidate_text(local_variant)
            suppress_cloud_text(text)
            emit(local_variant)
        elseif contains_cloud then
            local text = candidate_text(candidate)
            if text ~= "" and local_texts[text] then
                suppress_cloud_text(text)
            elseif cloud_count < env.cloud_config.max_candidates and emit(candidate) then
                cloud_count = cloud_count + 1
            end
        else
            emit(candidate)
        end
    end
end

M.filter = {
    init = filter_init,
    func = filter_func,
}

M._test = {
    current_request_target = current_request_target,
    response_matches_target = response_matches_target,
    remember_response = remember_response,
}

return M
