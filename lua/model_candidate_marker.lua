-- Keep Wanxiang/generated sentence candidates visibly marked while leaving
-- learned user phrases unmarked. The upstream is_in_user_dict filter is not
-- enabled, so this adds only the model marker and never restores "*".

local M = {}

function M.func(input, env)
    for cand in input:iter() do
        if cand.type == "sentence" then
            cand.comment = "∞"
        end
        yield(cand)
    end
end

return M
