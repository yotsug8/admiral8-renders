"use strict";
// Admiral 8: камера и интерфейс для записи роликов. Кадр сцены (a8_t): Lua шлёт a8_cam {x,y,z,dist,pitch,yaw};
// проигрывание (a8_play): таблицу a8_camkeys и старт a8_camplay — камера считается здесь каждый кадр.
(function () {
	for (var k in DotaDefaultUIElement_t) {
		try { GameUI.SetDefaultUIEnabled(DotaDefaultUIElement_t[k], false); } catch (e) {}
	}
	var hud = $.GetContextPanel().GetParent().GetParent().GetParent();
	try { hud.FindChildTraverse("HUDElements").style.visibility = "collapse"; } catch (e) {}
	function apply(x, y, z, dist, pitch, yaw, lerp) {
		GameUI.SetCameraPitchMin(pitch); GameUI.SetCameraPitchMax(pitch);
		GameUI.SetCameraYaw(yaw);
		GameUI.SetCameraDistance(dist);
		GameUI.SetCameraLookAtPositionHeightOffset(0);
		GameUI.SetCameraTargetPosition([x, y, z], lerp);
	}
	GameEvents.Subscribe("a8_cam", function (d) {
		apply(d.x, d.y, d.z, d.dist, d.pitch, d.yaw, d.lerp || -1);
		$.Msg("[a8] cam " + JSON.stringify(d));
	});
	// Проигрывание: таблица ключей камеры приходит один раз (частями), дальше камера ставится каждый кадр
	// по времени игры — раньше сервер слал её раз в тик, и кадр то получал два положения, то ни одного (рывки).
	var K = [], KF = 10, DUR = 0, START = null;
	GameEvents.Subscribe("a8_camkeys", function (d) {
		if (d.part == 0) K = [];
		var v = String(d.keys).split(" ").map(Number);
		for (var i = 0; i + 5 < v.length; i += 6) K.push(v.slice(i, i + 6));
		KF = d.kf; DUR = d.dur;
	});
	function cr(a, b, c, e, s) {          // Катмулл — Ром: скорость камеры без изломов на ключах
		return 0.5 * (2 * b + (c - a) * s + (2 * a - 5 * b + 4 * c - e) * s * s + (3 * b - a - 3 * c + e) * s * s * s);
	}
	function tick() {
		if (START === null || !K.length) return;
		var t = Game.GetGameTime() - START;
		if (t > DUR + 0.02) { START = null; return; }
		var f = Math.max(0, t * KF), i = Math.floor(f), s = f - i, n = K.length;
		var g = function (j) { return K[Math.max(0, Math.min(n - 1, j))]; };
		var c = [];
		for (var j = 0; j < 6; j++) c.push(cr(g(i - 1)[j], g(i)[j], g(i + 1)[j], g(i + 2)[j], s));
		apply(c[0], c[1], c[2], c[3], c[4], c[5], 0);
		$.Schedule(0, tick);
	}
	GameEvents.Subscribe("a8_camplay", function (d) { START = d.start; $.Msg("[a8] camplay " + K.length + " ключей"); tick(); });
	$.Msg("[a8] panorama ready");
})();
