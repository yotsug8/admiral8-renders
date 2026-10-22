-- Admiral 8: режиссёр сцен для роликов в движке доты.
-- Сцена — scripts/a8_scene.txt (генерирует tools/dota_engine/scene_*.py). Команды консоли:
--   a8_t <сек>     — поставить всех в момент времени (для проверки кадра)
--   a8_play        — проиграть сцену с начала (перед этим в консоли: startmovie <имя> tga)
--   a8_reload      — перечитать сцену; a8_time <0..1> — время суток; a8_where — справка по карте
print("[a8] addon loaded")
local MODEL = "models/a8/pudge/pudge_a8.vmdl"
local PARTS = { "back", "belt", "bracer", "hair", "leftarm", "leftweapon", "righthook", "weapon" }

function Precache(ctx)
	PrecacheModel(MODEL, ctx)
	for _, p in ipairs(PARTS) do PrecacheModel("models/heroes/pudge/" .. p .. ".vmdl", ctx) end
	PrecacheModel("models/development/invisiblebox.vmdl", ctx)
	-- деревья карты: в пользовательской игре их модели сами не подгружаются, и вместо деревьев остаются пни
	local tr = LoadKeyValues("scripts/a8_trees.txt")
	if tr then for _, m in pairs(tr.models) do PrecacheModel(m, ctx) end end
	PrecacheUnitByNameSync("npc_dota_hero_pudge", ctx)
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

function A8_Spawn(anim, pos)
	local p = SpawnEntityFromTableSynchronous("prop_dynamic", { model = MODEL, DefaultAnim = anim, origin = pos })
	for _, part in ipairs(PARTS) do
		local w = SpawnEntityFromTableSynchronous("prop_dynamic", { model = "models/heroes/pudge/" .. part .. ".vmdl", origin = pos })
		w:FollowEntity(p, true)
	end
	return p
end

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
	CustomGameEventManager:Send_ServerToAllClients("a8_cam", { x = x, y = y, z = z, dist = dist, pitch = pitch, yaw = yaw, h = 0, lerp = 1 })
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
		for _, v in pairs(a.anims) do local q = nums(v); anims[#anims + 1] = { t = q[1], s = q[2] } end
		table.sort(anims, function(p, q) return p.t < q.t end)
		local k0 = keys[0]
		A8_ACT[name] = { keys = keys, n = #keys, anims = anims, ent = A8_Spawn(anims[1].s, Vector(k0[1], k0[2], k0[3])) }
	end
	A8_CAMK = {}
	for i, v in pairs(A8_SC.camera) do A8_CAMK[tonumber(i)] = nums(v) end
	print("[a8] scene loaded, duration " .. A8_DUR)
end

local function sample(keys, t)
	local f = t * A8_KF; local i = math.floor(f); local k = f - i
	local a = keys[i] or keys[#keys]; local b = keys[i + 1] or a
	local r = {}
	for j = 1, 6 do r[j] = a[j] + (b[j] - a[j]) * k end
	return r
end

function A8_Pose(t)
	for _, a in pairs(A8_ACT) do
		local s = sample(a.keys, t)
		a.ent:SetAbsOrigin(Vector(s[1], s[2], s[3]))
		a.ent:SetAngles(s[4], s[5], s[6])
		local want = a.anims[1].s
		for _, e in ipairs(a.anims) do if t >= e.t then want = e.s end end
		if want ~= a.cur then a.ent:ResetSequence(want); a.cur = want end
	end
	local c = sample(A8_CAMK, t)
	A8_Cam(c[1], c[2], c[3], c[4], c[5], c[6])
end

-- Деревья: в пользовательской игре на карте доты кроны не рисуются (остаются пни) — ставим те же модели сами
function A8_FixTrees(cx, cy, r)
	local tr = LoadKeyValues("scripts/a8_trees.txt")
	if not tr then print("[a8] нет a8_trees.txt") return end
	for _, e in ipairs(A8_TREES or {}) do e:RemoveSelf() end
	A8_TREES = {}
	for _, v in pairs(tr.list) do
		local q = nums(v)
		if (q[1] - cx) ^ 2 + (q[2] - cy) ^ 2 < r * r then
			local e = SpawnEntityFromTableSynchronous("prop_dynamic", {
				model = tr.models[tostring(q[4])], origin = Vector(q[1], q[2], q[3]), angles = Vector(0, q[5], 0),
				modelscale = q[6], rendercolor = q[7] .. " " .. q[8] .. " " .. q[9], DefaultAnim = "idle" })
			if e then table.insert(A8_TREES, e) end
		end
	end
	print("[a8] деревья поставлены: " .. #A8_TREES)
end

function A8_Setup()
	local hero = PlayerResource:GetSelectedHeroEntity(0)
	if hero then hero:AddNoDraw(); hero:SetAbsOrigin(Vector(6000, 6000, 0)) end
	GameRules:SetTimeOfDay(0.5)
	A8_FixTrees(1516, -1660, 3200)
	A8_Load()
	A8_Pose(0)
	print("[a8] setup done")
end

Convars:RegisterCommand("a8_t", function(_, t) A8_PLAY = nil; for _, a in pairs(A8_ACT) do a.cur = nil end A8_Pose(tonumber(t) or 0) end, "кадр сцены в момент t", 0)
Convars:RegisterCommand("a8_reload", function()
	for _, a in pairs(A8_ACT or {}) do a.ent:RemoveSelf() end
	A8_Load(); A8_Pose(0)
end, "перечитать сцену", 0)
Convars:RegisterCommand("a8_time", function(_, v) GameRules:SetTimeOfDay(tonumber(v) or 0.5) print("[a8] day " .. tostring(GameRules:IsDaytime())) end, "время суток", 0)
Convars:RegisterCommand("a8_play", function()
	A8_PLAY = GameRules:GetGameTime()
	for _, a in pairs(A8_ACT) do a.cur = nil end
	GameRules:GetGameModeEntity():SetThink(function()
		if not A8_PLAY then return nil end
		local t = GameRules:GetGameTime() - A8_PLAY
		A8_Pose(math.min(t, A8_DUR))
		if t >= A8_DUR then print("[a8] play done") A8_PLAY = nil return nil end
		return 0
	end, "a8_play", 0)
	print("[a8] play")
end, "проиграть сцену", 0)
Convars:RegisterCommand("a8_where", function()
	for _, cls in ipairs({ "dota_item_rune_spawner_powerup", "dota_item_rune_spawner_bounty", "ent_dota_fountain" }) do
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
