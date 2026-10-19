/*
CoH Art Bridge - 3ds Max 2015 side.

Started by tools/art_bridge.py (3dsmax.exe -U MAXScript coh_bridge.ms) and left running.
Every 0.75 s it reads art/work/.preview_request.txt (written by the bridge) and:
  - when the part changes: resets the scene, imports the part's .obj, builds the tint material
    (Standard material, diffuse = RGB Multiply(base, Mix(Color1, Color2, mask))) and frames the
    viewports (perspective / top / front / right);
  - when a texture or setting changes: reloads the bitmaps and renders the preview sheet
    (two isometric corners + front/back/left/right/top/bottom) to the part's .preview/sheet.png,
    which the Photoshop "CoH Preview" panel displays.
*/

global cohBridge
global cohLogPath

fn cohLog msg =
(
	format "CoH bridge: %\n" msg
	if cohLogPath != undefined do
	(
		try ((dotNetClass "System.IO.File").AppendAllText cohLogPath ((localTime as string) + "  " + (msg as string) + "\r\n")) catch ()
	)
)

struct CohBridgeState
(
	requestPath,
	scriptPath,
	scriptStamp,
	objStamp = "",
	timer,
	lastRequest = "",
	lastStamp = "",
	part = undefined,
	settings = undefined,
	material = undefined,
	baseMap = undefined,
	maskMap = undefined,
	mixMap = undefined,
	rimMap = undefined,
	keyLight = undefined,
	fillLight = undefined,
	busy = false
)

fn cohFileStamp p =
(
	if p == undefined or p == "" or not doesFileExist p then return ""
	getFileModDate p
)

-- Request = #(keys, values): plain MAXScript arrays (no .NET collections to trip over).
fn cohReadRequest p =
(
	if not doesFileExist p then return undefined
	local f
	try (f = openFile p mode:"r") catch (return undefined)
	if f == undefined then return undefined
	local keys = #(), vals = #()
	while not eof f do
	(
		local l = readLine f
		local i = findString l "="
		if i != undefined do (append keys (substring l 1 (i - 1)); append vals (substring l (i + 1) -1))
	)
	close f
	#(keys, vals)
)

fn cohGet d k def =
(
	local i = findItem d[1] k
	if i == 0 then def else d[2][i]
)

fn cohColor s =
(
	-- "r,g,b" in 0-255
	local p = filterString s ","
	if p.count < 3 then return (color 180 180 180)
	color (p[1] as float) (p[2] as float) (p[3] as float)
)

fn cohBuildMaterial st req =
(
	local m = Standardmaterial name:"CoH Tint"
	m.shaderType = 1 -- Blinn
	m.specularLevel = 10
	m.glossiness = 20
	st.baseMap = Bitmaptexture filename:(cohGet req "color" "") name:"Base"
	local maskFile = cohGet req "mask" ""
	if maskFile != "" and doesFileExist maskFile then
	(
		st.maskMap = Bitmaptexture filename:maskFile name:"Mask"
		st.mixMap = Mix name:"Color1 / Color2 by mask"
		st.mixMap.color1 = cohColor (cohGet req "color1" "176,216,255")
		st.mixMap.color2 = cohColor (cohGet req "color2" "42,111,143")
		st.mixMap.mask = st.maskMap
		local mult = RGB_Multiply name:"x base"
		mult.map1 = st.baseMap
		mult.map2 = st.mixMap
		m.diffuseMap = mult
	)
	else
	(
		st.maskMap = undefined
		st.mixMap = undefined
		m.diffuseMap = st.baseMap
	)
	st.rimMap = Falloff name:"Rim glow"
	st.rimMap.color1 = black
	st.rimMap.color2 = color 160 225 255
	m.selfIllumMap = st.rimMap
	m.selfIllumMapEnable = false
	showTextureMap m on
	m
)

fn cohApplyLook st req =
(
	local look = cohGet req "look" "FLAT"
	local m = st.material
	if m == undefined then return false
	if st.mixMap != undefined do
	(
		st.mixMap.color1 = cohColor (cohGet req "color1" "176,216,255")
		st.mixMap.color2 = cohColor (cohGet req "color2" "42,111,143")
	)
	m.opacity = 100
	m.selfIllumMapEnable = false
	m.useSelfIllumColor = false
	m.selfIllumAmount = 0
	st.keyLight.on = true
	st.fillLight.on = true
	case look of
	(
		"FLAT": (m.selfIllumAmount = 100; st.keyLight.on = false; st.fillLight.on = false; backgroundColor = color 31 33 41; ambientColor = black)
		"LIT": (st.keyLight.rgb = color 255 247 235; st.keyLight.multiplier = 1.2; backgroundColor = color 89 94 107; ambientColor = color 95 98 108)
		"GHOST": (m.opacity = (cohGet req "ghost_opacity" "55") as float; m.selfIllumMapEnable = true
		          st.keyLight.rgb = color 190 230 255; st.keyLight.multiplier = 0.8; backgroundColor = color 15 20 31; ambientColor = color 45 55 70)
		"DUSK": (st.keyLight.rgb = color 255 158 82; st.keyLight.multiplier = 1.2; backgroundColor = color 77 46 71; ambientColor = color 85 60 85)
	)
	true
)

fn cohLights st =
(
	st.keyLight = Directionallight name:"CoH Key" multiplier:1.2 castShadows:false
	st.keyLight.transform = (matrix3 1) * (rotateXMatrix -50) * (rotateZMatrix 35)
	st.fillLight = Directionallight name:"CoH Fill" multiplier:0.45 castShadows:false rgb:(color 190 210 255)
	st.fillLight.transform = (matrix3 1) * (rotateXMatrix -60) * (rotateZMatrix -145)
)

fn cohFrameViewports =
(
	viewport.setLayout #layout_4
	local types = #(#view_persp_user, #view_top, #view_front, #view_right)
	for i = 1 to 4 do
	(
		viewport.activeViewport = i
		viewport.setType types[i]
		viewport.SetRenderLevel #smoothhighlights
		viewport.SetShowEdgeFaces false
	)
	viewport.activeViewport = 1
	max zoomext sel all
	clearSelection()
	completeRedraw()
)

fn cohRenderSheet st req =
(
	local out = cohGet req "sheet" ""
	if out == "" or geometry.count == 0 then return false
	local bb = #(geometry[1].min, geometry[1].max)
	for g in geometry do (bb[1] = [amin bb[1].x g.min.x, amin bb[1].y g.min.y, amin bb[1].z g.min.z]
	                      bb[2] = [amax bb[2].x g.max.x, amax bb[2].y g.max.y, amax bb[2].z g.max.z])
	local center = (bb[1] + bb[2]) / 2.0
	local diag = length (bb[2] - bb[1])
	-- Order matches the panel's labels: iso front, front, back, top / iso back, left, right, bottom.
	local dirs = #([1,-1,1], [0,-1,0], [0,1,0], [0,-0.001,1], [-1,1,-1], [-1,0,0], [1,0,0], [0,-0.001,-1])
	local cell = 320
	local sheet = bitmap (cell * 4) (cell * 2) color:backgroundColor
	local dist = diag * 3.0
	for i = 1 to dirs.count do
	(
		local d = normalize dirs[i]
		local tgt = Targetobject pos:center
		local cam = Targetcamera pos:(center + d * dist) target:tgt
		cam.orthoProjection = true
		cam.fov = 2.0 * atan ((diag * 0.52) / dist)
		local img = render camera:cam outputSize:[cell, cell] vfb:false
		local col = mod (i - 1) 4
		local row = (i - 1) / 4
		pasteBitmap img sheet [0, 0] [col * cell, row * cell]
		close img
		-- Deleting either half of a target camera removes both, so check before each delete.
		if isValidNode cam do delete cam
		if isValidNode tgt do delete tgt
	)
	sheet.filename = out + ".tmp.png"
	save sheet
	close sheet
	-- Atomic swap so the panel never reads a half-written file.
	if doesFileExist out do deleteFile out
	renameFile (out + ".tmp.png") out
	cohLog ("rendered sheet " + out)
	true
)

fn cohLoadPart st req =
(
	resetMaxFile #noPrompt
	local obj = cohGet req "obj" ""
	importFile obj #noPrompt
	cohLights st
	st.material = cohBuildMaterial st req
	for g in geometry do g.material = st.material
	cohApplyLook st req
	cohFrameViewports()
	st.part = cohGet req "part" ""
	cohLog ("loaded " + st.part)
)

fn cohTick =
(
	local st = cohBridge
	if st.busy then return ok
	-- Pick up edits to this script without restarting Max.
	if st.scriptPath != undefined and (getFileModDate st.scriptPath) != st.scriptStamp do
	(
		st.timer.Stop()
		cohLog "script changed, reloading"
		fileIn st.scriptPath
		return ok
	)
	st.busy = true
	try
	(
		local req = cohReadRequest st.requestPath
		if req != undefined do
		(
			local raw = ""
			for k in #("part", "obj", "color", "mask", "color1", "color2", "look", "ghost_opacity") do raw += k + ":" + (cohGet req k "") + ";"
			local stamp = (cohFileStamp (cohGet req "color" "")) + "|" + (cohFileStamp (cohGet req "mask" ""))
			local objStamp = cohFileStamp (cohGet req "obj" "")
			-- Reimport when the part or its mesh file changes.
			local partChanged = (cohGet req "part" "") != st.part or (findString st.lastRequest ("obj:" + (cohGet req "obj" "") + ";")) == undefined or objStamp != st.objStamp
			st.objStamp = objStamp
			local changed = raw != st.lastRequest or stamp != st.lastStamp
			-- Remember the request first, so a failed render isn't retried every tick.
			st.lastRequest = raw
			st.lastStamp = stamp
			if partChanged then
			(
				cohLoadPart st req
				cohRenderSheet st req
			)
			else if changed do
			(
				if st.baseMap != undefined do st.baseMap.reload()
				if st.maskMap != undefined do st.maskMap.reload()
				cohApplyLook st req
				completeRedraw()
				cohRenderSheet st req
			)
		)
	)
	catch (cohLog ("error: " + getCurrentException()))
	st.busy = false
	ok
)

(
	if cohBridge != undefined and cohBridge.timer != undefined do cohBridge.timer.Stop()
	local here = getFilenamePath (getSourceFileName())
	local root = pathConfig.normalizePath (here + "..\\..\\")
	local me = getSourceFileName()
	cohBridge = CohBridgeState requestPath:(root + "art\\work\\.preview_request.txt") scriptPath:me scriptStamp:(getFileModDate me)
	local t = dotNetObject "System.Windows.Forms.Timer"
	t.Interval = 750
	dotNet.addEventHandler t "Tick" (fn onTick s e = cohTick())
	cohBridge.timer = t
	t.Start()
	cohLogPath = root + "art\\work\\max_bridge.log"
	cohLog ("watching " + cohBridge.requestPath)
)
