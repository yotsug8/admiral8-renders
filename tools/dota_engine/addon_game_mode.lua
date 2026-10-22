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

function A8_Setup()
	local hero = PlayerResource:GetSelectedHeroEntity(0)
	if hero then hero:AddNoDraw(); hero:SetAbsOrigin(Vector(6000, 6000, 0)) end
	GameRules:SetTimeOfDay(0.5)
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
