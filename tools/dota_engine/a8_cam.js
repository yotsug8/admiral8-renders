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
		GameUI.SetCameraLookAtPositionHeightOffset(z);     // z — высота точки взгляда над землёй (крупные планы на уровне глаз)
		GameUI.SetCameraTargetPosition([x, y, 0], lerp);
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
		// склейка — скачок между соседними ключами: камера не сглаживается через неё (план держится до склейки)
		var cut = function (j) { var a = K[Math.max(0, Math.min(n - 1, j))], b = K[Math.max(0, Math.min(n - 1, j + 1))];
			return Math.abs(a[0] - b[0]) + Math.abs(a[1] - b[1]) > 120 || Math.abs(a[5] - b[5]) > 15 || Math.abs(a[3] - b[3]) > 120; };
		if (cut(i)) s = 0;
		var lo = i, hi = i + 1;
		while (lo > 0 && !cut(lo - 1) && lo > i - 1) lo--;
		while (hi < n - 1 && !cut(hi) && hi < i + 2) hi++;
		var g = function (j) { return K[Math.max(lo, Math.min(hi, Math.max(0, Math.min(n - 1, j))))]; };
		var c = [];
		for (var j = 0; j < 6; j++) c.push(cr(g(i - 1)[j], g(i)[j], g(i + 1)[j], g(i + 2)[j], s));
		apply(c[0], c[1], c[2], c[3], c[4], c[5], -1);   // −1 — мгновенно (0 у доты — плавный довод, на склейках камера не успевает)
		$.Schedule(0, tick);
	}
	GameEvents.Subscribe("a8_camplay", function (d) { START = d.start; $.Msg("[a8] camplay " + K.length + " ключей"); tick(); });
	$.Msg("[a8] panorama ready");
})();
