-- Admiral 8: режиссёр сцен для роликов в движке доты.
-- Сцена — scripts/a8_scene.txt (генерирует tools/dota_engine/scene_*.py). Команды консоли:
--   a8_t <сек>     — поставить всех в момент времени (для проверки кадра)
--   a8_play        — проиграть сцену с начала (перед этим в консоли: startmovie <имя> tga)
--   a8_reload      — перечитать сцену; a8_time <0..1> — время суток; a8_where — справка по карте
--   a8_black       — увести камеру (сразу после сцены: по этому скачку sky_comp.py находит её конец)
--   a8_mark <имя>  — метка в консольном логе
--   a8_anims <модель> <анимация...> — длительности анимаций любой модели (список имён — tools/dota_engine/anims.py)
--   a8_fx <частица> [x y z] — проиграть частицу (проверка); a8_map — высоты и проходимость карты в лог
-- Актёр сцены: model (по умолчанию Пудж мода), parts — носимые части, ground 1 — z ключей считается
-- от земли (GetGroundHeight), иначе z абсолютный (так стоят Пуджи 006 в реке). Частицы — блок fx.
print("[a8] addon loaded")
local MODEL = "models/a8/pudge/pudge_a8.vmdl"
local PARTS = { "back", "belt", "bracer", "hair", "leftarm", "leftweapon", "righthook", "weapon" }
for i, p in ipairs(PARTS) do PARTS[i] = "models/heroes/pudge/" .. p .. ".vmdl" end

local function list(t)            -- блок KV {"1" "a", "2" "b"} → массив по порядку номеров
	local r = {}
	for k, v in pairs(t or {}) do r[#r + 1] = { tonumber(k) or 0, v } end
	table.sort(r, function(a, b) return a[1] < b[1] end)
	for i, v in ipairs(r) do r[i] = v[2] end
	return r
end

function Precache(ctx)
	PrecacheModel(MODEL, ctx)
	for _, p in ipairs(PARTS) do PrecacheModel(p, ctx) end
	PrecacheModel("models/development/invisiblebox.vmdl", ctx)
	-- деревья карты: в пользовательской игре их модели сами не подгружаются, и вместо деревьев остаются пни
	local tr = LoadKeyValues("scripts/a8_trees.txt")
	if tr then for _, m in pairs(tr.models) do PrecacheModel(m, ctx) end end
	PrecacheUnitByNameSync("npc_dota_hero_pudge", ctx)
	-- всё, что нужно сцене: модели актёров, их части, частицы, герои (с героем грузятся его частицы)
	local sc = LoadKeyValues("scripts/a8_scene.txt")
	if sc then
		for _, a in pairs(sc.actors or {}) do
			if a.model then PrecacheModel(a.model, ctx) end
			for _, p in ipairs(list(a.parts)) do PrecacheModel(p, ctx) end
		end
		for _, f in pairs(sc.fx or {}) do PrecacheResource("particle", string.match(f, "^%S+%s+(%S+)"), ctx) end
		for _, h in ipairs(list(sc.heroes)) do PrecacheUnitByNameSync(h, ctx) end
	end
end

function Activate()
	local gm = GameRules:GetGameModeEntity()
	gm:SetCustomGameForceHero("npc_dota_hero_pudge")
	gm:SetFogOfWarDisabled(true)
	gm:SetDaynightCycleDisabled(true)
	gm:SetAnnouncerDisabled(true)
	GameRules:SetPreGameTime(0); GameRules:SetStrategyTime(0); GameRules:SetShowcaseTime(0); GameRules:SetHeroSelectionTime(0)
	GameRules:SetCustomGameSetupTimeout(0); GameRules:SetCustomGameSetupAutoLaunchDelay(0); GameRules:EnableCustomGameSetupAutoLaunch(true)
	ListenToGameEvent("game_rules_state_change", function() A8_State() end, nil)
	print("[a8] activated")
end

local function nums(s) local t = {} for v in string.gmatch(s, "%S+") do t[#t + 1] = tonumber(v) or v end return t end

function A8_Spawn(anim, pos, model, parts)
	local p = SpawnEntityFromTableSynchronous("prop_dynamic", { model = model or MODEL, DefaultAnim = anim, origin = pos })
	local ws = {}
	for _, part in ipairs(parts or PARTS) do
		local w = SpawnEntityFromTableSynchronous("prop_dynamic", { model = part, origin = pos })
		w:FollowEntity(p, true)
		ws[#ws + 1] = w
	end
	return p, ws
end

-- высота земли под точкой (у реки — дно)
function A8_Ground(x, y) return GetGroundHeight(Vector(x, y, 0), nil) end

function A8_State()
	local st = GameRules:State_Get()
	if (st == DOTA_GAMERULES_STATE_GAME_IN_PROGRESS or st == DOTA_GAMERULES_STATE_PRE_GAME) and not A8_DONE then
		A8_DONE = true
		GameRules:GetGameModeEntity():SetContextThink("a8_setup", function() A8_Setup() return nil end, 1.0)
	end
end

function A8_Cam(x, y, z, dist, pitch, yaw)
	if not A8_CAMT then
		A8_CAMT = SpawnEntityFromTableSynchronous("prop_dynamic", { model = "models/development/invisiblebox.vmdl", origin = Vector(x, y, z) })
		A8_CAMT:AddEffects(EF_NODRAW)
		PlayerResource:SetCameraTarget(0, A8_CAMT)
	end
	A8_CAMT:SetAbsOrigin(Vector(x, y, z))
	PlayerResource:SetCameraTarget(0, A8_CAMT)   -- заново каждый раз: иначе камера однажды срывается на героя
	CustomGameEventManager:Send_ServerToAllClients("a8_cam", { x = x, y = y, z = z, dist = dist, pitch = pitch, yaw = yaw, h = 0, lerp = A8_LERP or 0 })
end

-- Конец сцены в записи: на следующем тике после последнего кадра камера уводится — резкий скачок картинки,
-- по нему sky_comp.py отрезает ровно сцену. (Чёрным кадр не становится: высоту камеры дота берёт с земли.)
function A8_Black()
	local c = A8_CAMK and A8_CAMK[0] or { 1516, -1660 }
	A8_Cam(c[1], c[2], -400, 10, 89, 0)
end

function A8_Load()
	A8_SC = LoadKeyValues("scripts/a8_scene.txt")
	if not A8_SC then print("[a8] нет scripts/a8_scene.txt") return end
	A8_KF = tonumber(A8_SC.kf) or 10
	A8_DUR = tonumber(A8_SC.duration) or 10
	A8_ACT = {}
	for name, a in pairs(A8_SC.actors) do
		local keys, anims = {}, {}
		for i, v in pairs(a.keys) do keys[tonumber(i)] = nums(v) end
		-- анимация: "t имя [скорость]"
		for _, v in pairs(a.anims) do local q = nums(v); anims[#anims + 1] = { t = q[1], s = q[2], r = q[3] or 1 } end
		table.sort(anims, function(p, q) return p.t < q.t end)
		local k0 = keys[0]
		local parts = a.parts and list(a.parts) or (a.model and {} or nil)
		local ent, ws = A8_Spawn(anims[1].s, Vector(k0[1], k0[2], k0[3]), a.model, parts)
		A8_ACT[name] = { keys = keys, n = #keys, anims = anims, ent = ent, parts = ws, ground = tonumber(a.ground) == 1 }
	end
	A8_CAMK = {}
	for i, v in pairs(A8_SC.camera) do A8_CAMK[tonumber(i)] = nums(v) end
	-- частицы: "t частица x y z [длительность] [актёр]" — x y z в мире, или смещение от актёра, если он назван;
	-- z от земли. Длительность 0 — не гасить (частица кончится сама).
	A8_FX = {}
	for _, v in ipairs(list(A8_SC.fx)) do
		local q = nums(v)
		A8_FX[#A8_FX + 1] = { t = q[1], name = q[2], x = q[3] or 0, y = q[4] or 0, z = q[5] or 0, dur = q[6] or 0, who = q[7], to = q[8] }
	end
	print("[a8] scene loaded, duration " .. A8_DUR)
end

local function sample(keys, t)
	local f = t * A8_KF; local i = math.floor(f); local k = f - i
	local a = keys[i] or keys[#keys]; local b = keys[i + 1] or a
	local r = {}
	for j = 1, 6 do r[j] = a[j] + (b[j] - a[j]) * k end
	return r
end

function A8_Pose(t, nocam)
	for _, a in pairs(A8_ACT) do
		local s = sample(a.keys, t)
		local z = s[3] + (a.ground and A8_Ground(s[1], s[2]) or 0)
		a.ent:SetAbsOrigin(Vector(s[1], s[2], z))
		a.ent:SetAngles(s[4], s[5], s[6])
		local want = a.anims[1]
		for _, e in ipairs(a.anims) do if t >= e.t then want = e end end
		if want ~= a.cur then
			pcall(function() a.ent:ResetSequence(want.s) end); a.cur = want   -- у служебных моделей (острие крюка) анимаций нет
			if want.r ~= 1 or a.rate then   -- у prop_dynamic нет метода SetPlaybackRate — только вход сущности
				DoEntFireByInstanceHandle(a.ent, "SetPlaybackRate", tostring(want.r), 0, nil, nil); a.rate = want.r end
		end
	end
	if nocam then return end   -- проигрывание: камеру ставит интерфейс каждый кадр (a8_camkeys)
	local c = sample(A8_CAMK, t)
	A8_Cam(c[1], c[2], c[3], c[4], c[5], c[6])
end

-- таблица камеры интерфейсу частями (событие не может быть большим)
function A8_SendCamKeys()
	local n = #A8_CAMK; local part, buf, cnt = 0, {}, 0
	for i = 0, n do
		local c = A8_CAMK[i]
		buf[#buf + 1] = string.format("%.1f %.1f %.1f %.1f %.2f %.2f", c[1], c[2], c[3], c[4], c[5], c[6]); cnt = cnt + 1
		if cnt == 120 or i == n then
			CustomGameEventManager:Send_ServerToAllClients("a8_camkeys", { part = part, kf = A8_KF, dur = A8_DUR, keys = table.concat(buf, " ") })
			part = part + 1; buf = {}; cnt = 0
		end
	end
end

function A8_FxPlay(f)
	-- цепь (крюк Пуджа): от руки актёра who к актёру to, оба конца следуют за ними
	if f.to and f.who and A8_ACT[f.to] and A8_ACT[f.who] then
		local a, b = A8_ACT[f.who].ent, A8_ACT[f.to].ent
		local p = ParticleManager:CreateParticle(f.name, PATTACH_CUSTOMORIGIN, a)
		ParticleManager:SetParticleAlwaysSimulate(p)
		ParticleManager:SetParticleControlEnt(p, 0, a, PATTACH_POINT_FOLLOW, "attach_weapon_chain_rt", a:GetAbsOrigin(), true)
		ParticleManager:SetParticleControlEnt(p, 1, b, PATTACH_ABSORIGIN_FOLLOW, nil, b:GetAbsOrigin(), true)
		ParticleManager:SetParticleControl(p, 2, Vector(1600, 1300, 100))
		ParticleManager:SetParticleControl(p, 3, Vector(f.dur > 0 and f.dur or 2, 0, 0))
		ParticleManager:SetParticleControl(p, 4, Vector(1, 0, 0))
		ParticleManager:SetParticleControl(p, 5, Vector(0, 0, 0))
		ParticleManager:SetParticleControlEnt(p, 7, a, PATTACH_CUSTOMORIGIN, nil, a:GetOrigin(), true)
		print("[a8] fx цепь " .. f.name .. " " .. f.who .. " → " .. f.to)
		A8_FXP = A8_FXP or {}
		A8_FXP[#A8_FXP + 1] = p
		if f.dur > 0 then
			GameRules:GetGameModeEntity():SetContextThink("a8_fx" .. p, function()
				ParticleManager:DestroyParticle(p, false); ParticleManager:ReleaseParticleIndex(p) return nil end, f.dur)
		end
		return p
	end
	local pos = Vector(f.x, f.y, 0)
	local a = f.who and A8_ACT[f.who]
	if a then pos = a.ent:GetAbsOrigin() + Vector(f.x, f.y, 0) end
	pos.z = A8_Ground(pos.x, pos.y) + f.z
	local p = ParticleManager:CreateParticle(f.name, PATTACH_WORLDORIGIN, nil)
	ParticleManager:SetParticleControl(p, 0, pos)
	ParticleManager:SetParticleControl(p, 1, pos)
	print("[a8] fx " .. f.name .. " " .. tostring(pos))
	A8_FXP = A8_FXP or {}
	A8_FXP[#A8_FXP + 1] = p
	if f.dur > 0 then
		GameRules:GetGameModeEntity():SetContextThink("a8_fx" .. p, function()
			ParticleManager:DestroyParticle(p, false); ParticleManager:ReleaseParticleIndex(p) return nil end, f.dur)
	end
	return p
end

-- частицы, чьё время пришлось на (t0, t1]: при проигрывании каждая запускается один раз
function A8_FxStep(t0, t1)
	for _, f in ipairs(A8_FX or {}) do
		if f.t > t0 and f.t <= t1 then A8_FxPlay(f) end
	end
end

function A8_FxClear()
	for _, p in ipairs(A8_FXP or {}) do ParticleManager:DestroyParticle(p, true) end
	A8_FXP = {}
end

-- Деревья: в пользовательской игре модели деревьев с морфингом (*_vmorf) не рисуются — остаются пни.
-- Ставим на их места кино-версии тех же моделей (*_sfm, без морфинга) — scripts/a8_trees.txt
-- Деревья между камерой и сценой не ставятся (не закрывать кадр). Без блока trees в сцене — правило 006
-- (южнее y −1640 у реки); с блоком "trees" "cx cy r clear" — всё, что ближе clear к лучу камеры в любой момент.
A8_FRONT_Y = -1640
local function cam_pos(c)
	local p, y = math.rad(c[5]), math.rad(c[6])
	return c[1] + c[4] * math.sin(y) * math.cos(p), c[2] - c[4] * math.cos(y) * math.cos(p)
end
local function seg_dist(px, py, ax, ay, bx, by)
	local dx, dy = bx - ax, by - ay
	local k = math.max(0, math.min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy + 1e-9)))
	return math.sqrt((px - ax - k * dx) ^ 2 + (py - ay - k * dy) ^ 2)
end
local function in_front(x, y, clear)
	for i = 0, #A8_CAMK, 5 do
		local c = A8_CAMK[i]
		local ax, ay = cam_pos(c)
		if seg_dist(x, y, ax, ay, c[1], c[2]) < clear then return true end
	end
	return false
end
function A8_FixTrees(cx, cy, r, clear)
	local tr = LoadKeyValues("scripts/a8_trees.txt")
	if not tr then print("[a8] нет a8_trees.txt") return end
	for _, e in ipairs(A8_TREES or {}) do if IsValidEntity(e) then e:RemoveSelf() end end
	for _, h in ipairs(A8_HIDDEN or {}) do if IsValidEntity(h[1]) then h[1]:SetAbsOrigin(h[2]) end end
	A8_HIDDEN = {}
	A8_TREES = {}
	for _, v in pairs(tr.list) do
		local q = nums(v)
		local front
		if clear then front = in_front(q[1], q[2], clear)
		else front = q[2] < A8_FRONT_Y and math.abs(q[1] - cx) < 750 end
		if front and clear then                  -- убранное дерево: спрятать и его пень (дерево карты рисуется только пнём)
			for _, t in pairs(GridNav:GetAllTreesAroundPoint(Vector(q[1], q[2], q[3]), 40, true) or {}) do
				A8_HIDDEN = A8_HIDDEN or {}; table.insert(A8_HIDDEN, { t, t:GetAbsOrigin() })
				t:SetAbsOrigin(t:GetAbsOrigin() - Vector(0, 0, 3000))   -- NODRAW дерево карты не прячет: уводим под землю
			end
		end
		if (q[1] - cx) ^ 2 + (q[2] - cy) ^ 2 < r * r and not front then
			local e = SpawnEntityFromTableSynchronous("prop_dynamic", {
				model = tr.models[tostring(q[4])], origin = Vector(q[1], q[2], q[3]), angles = Vector(0, q[5], 0),
				modelscale = q[6], rendercolor = q[7] .. " " .. q[8] .. " " .. q[9] })
			if e then table.insert(A8_TREES, e) end
		end
	end
	print("[a8] деревья поставлены: " .. #A8_TREES .. ", пней спрятано: " .. #(A8_HIDDEN or {}))
end

function A8_Setup()
	local hero = PlayerResource:GetSelectedHeroEntity(0)
	if hero then hero:AddNoDraw(); hero:SetAbsOrigin(Vector(6000, 6000, 0)) end
	A8_NoCreeps()
	GameRules:SetTimeOfDay(0.5)
	A8_Load()
	A8_Trees()
	A8_Pose(0)
	print("[a8] setup done")
end

-- крипы линий в сцене не нужны: не выпускать и убрать уже вышедших (по ним стреляют вышки)
function A8_NoCreeps()
	pcall(function() GameRules:SetCreepSpawningEnabled(false) end)
	SendToConsole("dota_creeps_no_spawning 1")
	local n = 0
	for _, cls in ipairs({ "npc_dota_creep_lane", "npc_dota_creep_siege" }) do
		for _, e in pairs(Entities:FindAllByClassname(cls)) do e:RemoveSelf(); n = n + 1 end
	end
	print("[a8] крипов убрано: " .. n)
end

-- деревья вокруг сцены: блок "trees" "cx cy r clear" или, без него, как в 006 (у нижней руны)
function A8_Trees()
	local q = A8_SC and A8_SC.trees and nums(A8_SC.trees)
	if q then A8_FixTrees(q[1], q[2], q[3], q[4]) else A8_FixTrees(1516, -1660, 3200) end
end

Convars:RegisterCommand("a8_t", function(_, t) A8_PLAY = nil; A8_FxClear(); for _, a in pairs(A8_ACT) do a.cur = nil end A8_Pose(tonumber(t) or 0) end, "кадр сцены в момент t", 0)
Convars:RegisterCommand("a8_reload", function()
	A8_PLAY = nil; A8_FxClear()
	for _, a in pairs(A8_ACT or {}) do
		for _, w in ipairs(a.parts or {}) do w:RemoveSelf() end
		a.ent:RemoveSelf()
	end
	A8_NoCreeps(); A8_Load(); A8_Trees(); A8_Pose(0)
end, "перечитать сцену", 0)
Convars:RegisterCommand("a8_time", function(_, v) GameRules:SetTimeOfDay(tonumber(v) or 0.5) print("[a8] day " .. tostring(GameRules:IsDaytime())) end, "время суток", 0)
Convars:RegisterCommand("a8_play", function()
	A8_FxClear()
	A8_SendCamKeys()
	PlayerResource:SetCameraTarget(0, nil)   -- иначе серверная цель и интерфейс тянут камеру по очереди
	A8_PLAY = GameRules:GetGameTime()
	CustomGameEventManager:Send_ServerToAllClients("a8_camplay", { start = A8_PLAY })
	for _, a in pairs(A8_ACT) do a.cur = nil end
	local prev = -1
	GameRules:GetGameModeEntity():SetThink(function()
		if not A8_PLAY then return nil end
		local t = GameRules:GetGameTime() - A8_PLAY
		A8_Pose(math.min(t, A8_DUR), true)
		A8_FxStep(prev, math.min(t, A8_DUR)); prev = t
		if t >= A8_DUR + 2 / 30 then   -- последняя поза держится ещё 2 кадра: запись не захватывает кадр после сцены
			A8_PLAY = nil
			GameRules:GetGameModeEntity():SetContextThink("a8_black", function() A8_Black() print("[a8] play done") return nil end, 0)
			return nil
		end
		return 0
	end, "a8_play", 0)
	print("[a8] play")
end, "проиграть сцену", 0)
Convars:RegisterCommand("a8_notrees", function()
	for _, e in ipairs(A8_TREES or {}) do if IsValidEntity(e) then e:AddEffects(EF_NODRAW) end end
end, "спрятать поставленные деревья (проверка)", 0)
Convars:RegisterCommand("a8_lerp", function(_, v) A8_LERP = tonumber(v) end, "плавность камеры (проверка)", 0)
Convars:RegisterCommand("a8_pos", function()
	for k, a in pairs(A8_ACT or {}) do print("[a8p] " .. k .. " " .. tostring(a.ent:GetAbsOrigin()) .. " yaw " .. a.ent:GetAnglesAsVector().y) end
	if A8_CAMT then print("[a8p] camera target " .. tostring(A8_CAMT:GetAbsOrigin())) end
end, "где актёры", 0)
Convars:RegisterCommand("a8_black", function() A8_PLAY = nil A8_Black() end, "чёрный кадр-метка", 0)
Convars:RegisterCommand("a8_mark", function(_, s) print("[a8] mark " .. tostring(s)) end, "метка в логе", 0)
Convars:RegisterCommand("a8_where", function()
	for _, cls in ipairs({ "dota_item_rune_spawner_powerup", "dota_item_rune_spawner_bounty", "ent_dota_fountain",
			"npc_dota_tower", "npc_dota_barracks", "npc_dota_fort", "npc_dota_filler", "npc_dota_building",
			"ent_dota_shop", "npc_dota_watch_tower", "npc_dota_roshan_spawner" }) do
		for _, e in pairs(Entities:FindAllByClassname(cls)) do print("[a8w] " .. cls .. " " .. tostring(e:GetAbsOrigin())) end
	end
end, "где что на карте", 0)
Convars:RegisterCommand("a8_cam", function(_, x, y, z, dist, pitch, yaw)
	A8_PLAY = nil
	A8_Cam(tonumber(x), tonumber(y), tonumber(z), tonumber(dist), tonumber(pitch), tonumber(yaw))
end, "камера вручную: x y z дальность наклон поворот", 0)
Convars:RegisterCommand("a8_dur", function(_, ...)
	local e = nil; for _, a in pairs(A8_ACT) do e = a.ent break end
	for _, n in ipairs({ ... }) do print("[a8d] " .. n .. " " .. tostring(e:SequenceDuration(n))) end
end, "длительности анимаций", 0)
-- длительности анимаций любой модели: a8_anims <модель> <имя> [имя ...] (имена — из anims.py)
Convars:RegisterCommand("a8_anims", function(_, model, ...)
	local e = SpawnEntityFromTableSynchronous("prop_dynamic", { model = model, origin = Vector(6000, 6000, 0) })
	if not e then print("[a8a] нет модели " .. tostring(model)) return end
	for _, n in ipairs({ ... }) do print("[a8a] " .. n .. " " .. tostring(e:SequenceDuration(n))) end
	print("[a8a] done")
	e:RemoveSelf()
end, "длительности анимаций модели", 0)
-- проверка частицы: a8_fx <частица> [x y z] (по умолчанию — у первого актёра), гаснет через 4 с
Convars:RegisterCommand("a8_fx", function(_, name, x, y, z)
	local f = { name = name, x = tonumber(x) or 0, y = tonumber(y) or 0, z = tonumber(z) or 0, dur = 4 }
	if not x then for k, _ in pairs(A8_ACT or {}) do f.who = k break end end
	A8_FxPlay(f)
end, "проиграть частицу", 0)
-- карта для площадки: высота земли и проходимость с шагом S в квадрате ±R. Строки в лог:
--   [a8m] y h1 h2 ...   — высоты;   [a8n] y 0120...  — 0 проходимо, 1 занято (скалы, здания), 2 дерево
Convars:RegisterCommand("a8_map", function(_, step, rad)
	local S, R = tonumber(step) or 64, tonumber(rad) or 8192
	for y = R, -R, -S do
		local h, n = {}, {}
		for x = -R, R, S do
			local p = Vector(x, y, 0)
			h[#h + 1] = string.format("%d", GetGroundHeight(p, nil))
			local c = "0"
			if not GridNav:IsTraversable(p) or GridNav:IsBlocked(p) then c = "1" end
			if GridNav:IsNearbyTree(p, S / 2, true) then c = "2" end
			n[#n + 1] = c
		end
		print("[a8m] " .. y .. " " .. table.concat(h, " "))
		print("[a8n] " .. y .. " " .. table.concat(n))
	end
	print("[a8m] done " .. S .. " " .. R)
end, "высоты и проходимость карты", 0)
Convars:RegisterCommand("a8_trees", function()
	local all, up = 0, 0
	for _, t in pairs(Entities:FindAllByClassname("ent_dota_tree")) do all = all + 1; if t:IsStanding() then up = up + 1 end end
	print("[a8tr] деревьев " .. all .. ", стоят " .. up .. ", время " .. GameRules:GetTimeOfDay() .. ", день " .. tostring(GameRules:IsDaytime()))
end, "деревья и время", 0)
-- свой свет: дневные настройки стороны Света (default_RF), вокруг сцены
Convars:RegisterCommand("a8_light", function(_, inner, outer, scale)
	if A8_LIGHT then A8_LIGHT:RemoveSelf() end
	local c = A8_CAMK and A8_CAMK[0] or { 1516, -1660 }
	A8_LIGHT = SpawnEntityFromTableSynchronous("ent_dota_lightinfo", {
		origin = Vector(c[1], c[2], 300), inner_radius = tonumber(inner) or 3000, outer_radius = tonumber(outer) or 6000,
		light_direction_day = "66 0 0", color_day = "216 208 207", light_scale_day = tonumber(scale) or 5,
		ambient_color_day = "63 144 169", ambient_scale_day = 5, ambient_direction_day = "0 23 0",
		shadow_color_day = "230 175 177", shadow_scale_day = 1, shadow_ground_scale_day = 1, shadow_secondary_color_day = "230 175 177",
		specular_color_day = "81 196 232", specular_direction_day = "64 283 0", specular_power_day = -1,
		fog_color_day = "149 239 255", fog_start_day = 1250, fog_end_day = 4500,
		skybox_material_day = "materials/skybox/sky_dota_000.vmat", skybox_tint_color_day = "255 255 255 0",
		height_fog_color_day = "199 229 248", height_fog_density_day = 0,
		color_night = "216 208 207", light_scale_night = 5, ambient_color_night = "63 144 169", ambient_scale_night = 5,
	})
	print("[a8] light " .. tostring(A8_LIGHT))
end, "свой дневной свет", 0)
Convars:RegisterCommand("a8_treemodels", function()
	local m = {}
	for _, t in pairs(Entities:FindAllByClassname("ent_dota_tree")) do local n = t:GetModelName() m[n] = (m[n] or 0) + 1 end
	for n, c in pairs(m) do print("[a8tm] " .. c .. " " .. n) end
end, "модели деревьев", 0)
Convars:RegisterCommand("a8_testtree", function(_, model, x, y)
	PrecacheModelAsync = PrecacheModelAsync
	local e = SpawnEntityFromTableSynchronous("prop_dynamic", { model = model, origin = Vector(tonumber(x), tonumber(y), 0) })
	print("[a8tt] " .. model .. " -> " .. tostring(e) .. " " .. tostring(e and e:GetModelName()))
end, "тест модели дерева", 0)
Convars:RegisterCommand("a8_temptree", function(_, x, y, model)
	local p = Vector(tonumber(x), tonumber(y), 0)
	local t = model and CreateTempTreeWithModel(p, 600, model) or CreateTempTree(p, 600)
	print("[a8tt] temp tree " .. tostring(t) .. " " .. tostring(t and t:GetModelName()))
end, "временное дерево", 0)
Convars:RegisterCommand("a8_sky", function(_, mat, tint)
	if A8_SKY then A8_SKY:RemoveSelf() end
	A8_SKY = SpawnEntityFromTableSynchronous("env_sky", { skyname = mat or "materials/skybox/sky_dota_000.vmat", tint_color = tint or "255 255 255", brightnessscale = 1, StartDisabled = 0 })
	print("[a8] sky " .. tostring(A8_SKY))
end, "небо", 0)
