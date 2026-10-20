/*
CoH Art Bridge - 3ds Max 2015 side.

Started by tools/art_bridge.py (3dsmax.exe -U MAXScript coh_bridge.ms) and left running.
Several times a second it reads art/work/.preview_request.txt (written by the bridge) and:
  - when the part changes: resets the scene, imports the part's .obj, builds the tint material
    (Standard material, diffuse = RGB Multiply(base, Mix(Color1, Color2, mask))) and frames the
    viewports (perspective / top / front / right);
  - when a texture or setting changes: reloads the bitmaps and renders the preview sheet
    (two isometric corners + front/back/left/right/top/bottom) to the part's .preview/sheet.png,
    which the CoH Art Bridge app shows;
  - when the Photoshop "CoH Preview" panel orbits (it writes the part's .preview/orbit.txt): turns the
    Orthographic / Realistic viewport to that angle and saves exactly what it shows to .preview/view.png,
    which the panel displays.
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
	lastOrbit = "",
	viewCam = undefined,
	viewTgt = undefined,
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
	-- Frame the mesh only; plain Zoom Extents also fits the light icons, which dwarf small props.
	-- "zoomext sel all" skipped the fourth viewport, so frame each one while it is active.
	select (geometry as array)
	for i = 1 to 4 do
	(
		viewport.activeViewport = i
		viewport.SetRenderLevel #smoothhighlights
		max zoomext sel
	)
	viewport.activeViewport = 1
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

-- Swap a finished file into place in one step (File.Replace), so a reader never finds the file
-- missing or half-written. The first time there's nothing to replace, so it's a plain move.
fn cohPublish tmp out =
(
	local io = dotNetClass "System.IO.File"
	-- Replace needs a backup path (MAXScript can't pass null); it's overwritten each time.
	try (if io.Exists out then io.Replace tmp out (out + ".bak") else io.Move tmp out)
	catch
	(
		cohLog ("atomic replace failed, falling back: " + getCurrentException())
		if doesFileExist out do deleteFile out
		renameFile tmp out
	)
)

-- Windows parks minimized windows at -32000, -32000.
fn cohMaxMinimized =
(
	local r = try (windows.getWindowPos (windows.getMAXHWND())) catch (undefined)
	r != undefined and r.x < -10000
)

fn cohSceneBounds =
(
	if geometry.count == 0 then return undefined
	local bb = #(geometry[1].min, geometry[1].max)
	for g in geometry do (bb[1] = [amin bb[1].x g.min.x, amin bb[1].y g.min.y, amin bb[1].z g.min.z]
	                      bb[2] = [amax bb[2].x g.max.x, amax bb[2].y g.max.y, amax bb[2].z g.max.z])
	bb
)

-- Orbit = #(yaw, pitch, zoom, draft) from the panel's .preview/orbit.txt. Yaw 0 looks at the
-- front (from -Y). draft is true while the panel is dragging: smaller, faster frames.
fn cohReadOrbit req =
(
	local o = cohReadRequest ((getFilenamePath (cohGet req "sheet" "")) + "orbit.txt")
	if o == undefined then return #(35.0, 25.0, 1.0, false)
	#((cohGet o "yaw" "35") as float, (cohGet o "pitch" "25") as float, (cohGet o "zoom" "1") as float,
	  (cohGet o "quality" "final") == "draft")
)

-- Overlays (grid, ViewCube, viewport labels, light icons) would end up in the captured view.
fn cohCleanViewport =
(
	try (viewport.setGridVisibility #all false) catch ()
	try (ViewCubeOps.Visibility = false) catch ()
	try (ViewportButtonMgr.EnableButtons = false) catch ()
	hideByCategory.lights = true
	hideByCategory.cameras = true
	hideByCategory.helpers = true
)

-- Seen through a hidden orthographic camera so the scale never changes while orbiting, then
-- cropped to a centered square (which also drops the axis tripod in the corner).
fn cohRenderView st req orbit =
(
	-- Always published as view.frame (JPEG for drafts, PNG for final frames; the panel sniffs which).
	local out = (getFilenamePath (cohGet req "sheet" "")) + "view.frame"
	local draft = orbit[4]
	local tmp = out + (if draft then ".tmp.jpg" else ".tmp.png")
	local bb = cohSceneBounds()
	if bb == undefined then return false
	local center = (bb[1] + bb[2]) / 2.0
	local radius = (length (bb[2] - bb[1])) / 2.0
	local yaw = orbit[1], pitch = amax -89.0 (amin 89.0 orbit[2]), zoom = amax 0.1 orbit[3]
	local z = normalize [(cos pitch) * (sin yaw), -(cos pitch) * (cos yaw), sin pitch]
	local x = normalize (cross [0, 0, 1] z)
	local y = cross z x
	local dist = radius * 4.0
	-- Same camera setup as the preview sheet (target camera, orthographic), kept between frames.
	if st.viewCam == undefined or not isValidNode st.viewCam do
	(
		st.viewTgt = Targetobject name:"CoH View Target"
		st.viewCam = Targetcamera name:"CoH View" target:st.viewTgt orthoProjection:true
	)
	st.viewTgt.pos = center
	st.viewCam.pos = center + z * dist
	viewport.activeViewport = 1
	if viewport.getCamera() != st.viewCam do viewport.setCamera st.viewCam
	try ((NitrousGraphicsManager.GetActiveViewportSetting()).VisualStyleMode = #Realistic) catch ()
	-- A minimized (or tiny) Max doesn't draw its viewports, so render that one view instead.
	local w = gw.getWinSizeX(), h = gw.getWinSizeY()
	local sq
	if (cohMaxMinimized()) or w < 128 or h < 128 then
	(
		st.viewCam.fov = 2.0 * atan ((radius * 1.08 / zoom) / dist)
		local size = if draft then 360 else 720
		local aa = try (renderers.current.antiAliasing) catch (undefined)
		if draft and aa != undefined do renderers.current.antiAliasing = false
		sq = render camera:st.viewCam outputSize:[size, size] vfb:false
		if aa != undefined do renderers.current.antiAliasing = aa
	)
	else
	(
		-- Fit the bounding sphere (plus a margin) to the square's height; the camera FOV is horizontal.
		st.viewCam.fov = 2.0 * atan ((radius * 1.08 / zoom * (w as float) / h) / dist)
		completeRedraw()
		local dib = gw.getViewportDib()
		local side = amin dib.width dib.height
		sq = bitmap side side
		pasteBitmap dib sq (box2 ((dib.width - side) / 2) ((dib.height - side) / 2) side side) [0, 0]
		close dib
	)
	sq.filename = tmp
	save sq quiet:true
	close sq
	cohPublish tmp out
	true
)

-- Build the mesh ourselves instead of using Max's OBJ importer: the importer welds vertices that
-- share a position, but CoH splits vertices along hard edges and UV seams, so welding smooths
-- across those edges (dark diagonal halves on flat faces). Vertices, UVs and the game's normals
-- are kept exactly. OBJ is Y-up; Max is Z-up, so (x, y, z) -> (x, -z, y).
fn cohImportObj path =
(
	local verts = #(), tverts = #(), norms = #(), faces = #()
	local f = openFile path mode:"r"
	if f == undefined then return undefined
	while not eof f do
	(
		local tok = filterString (readLine f) " "
		if tok.count > 0 do
		(
			case tok[1] of
			(
				"v": append verts [tok[2] as float, -(tok[4] as float), tok[3] as float]
				"vt": append tverts [tok[2] as float, tok[3] as float, 0]
				"vn": append norms (normalize [tok[2] as float, -(tok[4] as float), tok[3] as float])
				"f": append faces [(filterString tok[2] "/")[1] as integer, (filterString tok[3] "/")[1] as integer, (filterString tok[4] "/")[1] as integer]
			)
		)
	)
	close f
	local m = mesh vertices:verts faces:faces name:(getFilenameFile path)
	for i = 1 to faces.count do setFaceSmoothGroup m i 1
	if tverts.count == verts.count do
	(
		setNumTVerts m tverts.count
		for i = 1 to tverts.count do setTVert m i tverts[i]
		buildTVFaces m
		for i = 1 to faces.count do setTVFace m i faces[i]
	)
	update m
	if norms.count == verts.count do
	(
		-- Edit Normals needs the object selected in the Modify panel.
		select m
		max modify mode
		local en = Edit_Normals()
		addModifier m en
		modPanel.setCurrentObject en
		for fi = 1 to faces.count do
			for c = 1 to 3 do
			(
				local nid = en.GetNormalID fi c
				en.SetNormal nid norms[en.GetVertexID fi c]
				en.SetNormalExplicit nid explicit:true
			)
		max create mode
		clearSelection()
	)
	m
)

fn cohLoadPart st req =
(
	resetMaxFile #noPrompt
	local obj = cohGet req "obj" ""
	cohImportObj obj
	cohLights st
	st.material = cohBuildMaterial st req
	for g in geometry do g.material = st.material
	cohApplyLook st req
	cohFrameViewports()
	cohCleanViewport()
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
			-- The orbit file's text, not its timestamp: file times only resolve to the second.
			local orbit = cohReadOrbit req
			local orbitRaw = (orbit as string)
			local orbitChanged = orbitRaw != st.lastOrbit
			st.lastOrbit = orbitRaw
			if partChanged then
			(
				cohLoadPart st req
				cohRenderSheet st req
				cohRenderView st req orbit
			)
			else if changed then
			(
				if st.baseMap != undefined do st.baseMap.reload()
				if st.maskMap != undefined do st.maskMap.reload()
				cohApplyLook st req
				completeRedraw()
				cohRenderView st req orbit
				cohRenderSheet st req
			)
			else if orbitChanged do cohRenderView st req orbit
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
	t.Interval = 50
	dotNet.addEventHandler t "Tick" (fn onTick s e = cohTick())
	cohBridge.timer = t
	t.Start()
	cohLogPath = root + "art\\work\\max_bridge.log"
	cohLog ("watching " + cohBridge.requestPath)
)
