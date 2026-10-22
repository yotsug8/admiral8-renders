-- Admiral 8: сцены роликов в движке доты. Кадр — один Пудж со своей анимацией в реке (проба).
print("[a8] addon loaded")
local MODEL = "models/a8/pudge/pudge_a8.vmdl"
local PARTS = { "back", "belt", "bracer", "hair", "leftarm", "leftweapon", "righthook", "weapon" }

function Precache(ctx)
	PrecacheModel(MODEL, ctx)
	for _, p in ipairs(PARTS) do PrecacheModel("models/heroes/pudge/" .. p .. ".vmdl", ctx) end
	PrecacheUnitByNameSync("npc_dota_hero_pudge", ctx)
end

function Activate()
	local gm = GameRules:GetGameModeEntity()
	gm:SetCustomGameForceHero("npc_dota_hero_pudge")
	gm:SetFogOfWarDisabled(true)
	gm:SetDaynightCycleDisabled(true)
	gm:SetAnnouncerDisabled(true)
	GameRules:SetPreGameTime(0)
	GameRules:SetStrategyTime(0)
	GameRules:SetShowcaseTime(0)
	GameRules:SetHeroSelectionTime(0)
	GameRules:SetCustomGameSetupTimeout(0)
	GameRules:SetCustomGameSetupAutoLaunchDelay(0)
	GameRules:EnableCustomGameSetupAutoLaunch(true)
	GameRules:SetCreepMinimapIconScale(0)
	ListenToGameEvent("game_rules_state_change", function() A8_State() end, nil)
	print("[a8] activated")
end

function A8_Spawn(name, anim, pos, yaw, rate)
	local p = SpawnEntityFromTableSynchronous("prop_dynamic", { model = MODEL, DefaultAnim = anim, origin = pos, angles = Vector(0, yaw, 0) })
	-- скорость проигрывания задаётся в модели
	for _, part in ipairs(PARTS) do
		local w = SpawnEntityFromTableSynchronous("prop_dynamic", { model = "models/heroes/pudge/" .. part .. ".vmdl", origin = pos })
		w:FollowEntity(p, true)
	end
	print("[a8] spawned " .. name .. " seq " .. tostring(p:GetSequence()))
	return p
end

function A8_State()
	local st = GameRules:State_Get()
	print("[a8] state " .. tostring(st))
	if st == DOTA_GAMERULES_STATE_GAME_IN_PROGRESS or st == DOTA_GAMERULES_STATE_PRE_GAME then
		if A8_DONE then return end
		A8_DONE = true
		GameRules:SetTimeOfDay(0.5)
		GameRules:GetGameModeEntity():SetContextThink("a8_setup", function() A8_Setup() return nil end, 1.0)
	end
end

function A8_Cam(x, y, z, dist, pitch, yaw, h)
	A8_CAMP = { x = x, y = y, z = z, dist = dist, pitch = pitch, yaw = yaw, h = h or 0, lerp = 1 }
	-- камера в доте следует за объектом: невидимая «мишень» в нужной точке
	if not A8_CAMT then
		A8_CAMT = SpawnEntityFromTableSynchronous("prop_dynamic", { model = "models/development/invisiblebox.vmdl", origin = Vector(x, y, z) })
		A8_CAMT:AddEffects(EF_NODRAW)
	end
	A8_CAMT:SetAbsOrigin(Vector(x, y, z))
	PlayerResource:SetCameraTarget(0, A8_CAMT)
	CustomGameEventManager:Send_ServerToAllClients("a8_cam", A8_CAMP)
end

function A8_Setup()
	-- место Пуджа P1 из сцены Blender: x = -By*39.37, y = Bx*39.37
	local c = GetGroundPosition(Vector(1520, -1450, 0), nil)   -- настоящая вода у нижней руны
	print("[a8] ground " .. tostring(c))
	A8_PUDGE = A8_Spawn("swim", "a8_swim", c + Vector(0, 0, -40), 200, 1.0)
	local hero = PlayerResource:GetSelectedHeroEntity(0)
	if hero then hero:AddNoDraw(); hero:SetAbsOrigin(Vector(6000, 6000, 0)) end
	A8_Cam(c.x, c.y, c.z, 1000, 40, 0, 0)
	local gm = GameRules:GetGameModeEntity()
	gm:SetContextThink("a8_shot1", function() SendToConsole("screenshot") print("[a8] shot") return nil end, 4.0)
	gm:SetContextThink("a8_shot2", function() SendToConsole("screenshot") print("[a8] shot") return nil end, 6.0)
	Convars:RegisterCommand("a8_cam", function(_, x, y, z, dist, pitch, yaw, h)
		A8_Cam(tonumber(x), tonumber(y), tonumber(z), tonumber(dist), tonumber(pitch), tonumber(yaw), tonumber(h or 0))
	end, "камера: x y z дальность наклон поворот [высота]", 0)
	Convars:RegisterCommand("a8_put", function(_, x, y, dz, yaw, anim)
		local g = GetGroundPosition(Vector(tonumber(x), tonumber(y), 0), nil)
		A8_PUDGE:SetAbsOrigin(g + Vector(0, 0, tonumber(dz)))
		A8_PUDGE:SetAngles(0, tonumber(yaw), 0)
		if anim then A8_PUDGE:ResetSequence(anim) end
		print("[a8] put " .. tostring(g))
	end, "Пудж: x y dz поворот [анимация]", 0)
	print("[a8] setup done")
end

Convars:RegisterCommand("a8_where", function()
	for _, cls in ipairs({ "dota_item_rune_spawner_powerup", "dota_item_rune_spawner_bounty", "npc_dota_roshan_spawner", "npc_dota_unit_twin_gate", "ent_dota_fountain" }) do
		for _, e in pairs(Entities:FindAllByClassname(cls)) do print("[a8w] " .. cls .. " " .. tostring(e:GetAbsOrigin())) end
	end
	if A8_PUDGE then print("[a8w] pudge " .. tostring(A8_PUDGE:GetAbsOrigin())) end
	for x = -1500, 1500, 500 do
		local row = ""
		for y = -1500, 1500, 500 do row = row .. string.format("%5d", math.floor(GetGroundHeight(Vector(x, y, 0), nil))) end
		print("[a8w] h x=" .. x .. " " .. row)
	end
end, "где что на карте", 0)
