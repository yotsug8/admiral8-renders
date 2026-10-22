"use strict";
// Admiral 8: камера и интерфейс для записи роликов. Lua шлёт событие a8_cam {x,y,z,dist,pitch,yaw}.
(function () {
	for (var k in DotaDefaultUIElement_t) {
		try { GameUI.SetDefaultUIEnabled(DotaDefaultUIElement_t[k], false); } catch (e) {}
	}
	var hud = $.GetContextPanel().GetParent().GetParent().GetParent();
	try { hud.FindChildTraverse("HUDElements").style.visibility = "collapse"; } catch (e) {}
	GameEvents.Subscribe("a8_cam", function (d) {
		GameUI.SetCameraPitchMin(d.pitch); GameUI.SetCameraPitchMax(d.pitch);
		GameUI.SetCameraYaw(d.yaw);
		GameUI.SetCameraDistance(d.dist);
		GameUI.SetCameraLookAtPositionHeightOffset(d.h || 0);
		GameUI.SetCameraTargetPosition([d.x, d.y, d.z], d.lerp || -1);
		$.Msg("[a8] cam " + JSON.stringify(d));
	});
	$.Msg("[a8] panorama ready");
})();
