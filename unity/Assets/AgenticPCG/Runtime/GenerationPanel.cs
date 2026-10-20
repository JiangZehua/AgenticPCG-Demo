using System;
using System.Collections.Concurrent;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using UnityEngine;

namespace AgenticPCG
{
    // Local desktop UI. Python owns credentials, model calls, evaluation and commitment.
    public class GenerationPanel : MonoBehaviour
    {
        [Serializable] class RequestHeader
        {
            public int schema_version = 1;
            public string domain = "keydoor", instruction;
        }
        [Serializable] class Targets
        {
            public int min_path_length, max_path_length, hazard_count;
            public int[] zone_hazards;
        }
        [Serializable] class PreparedRequest
        {
            public ResolvedRequest request;
            public ControlFlags controls;
        }
        [Serializable] class ResolvedRequest
        {
            public string instruction;
            public Targets targets;
        }
        [Serializable] class ControlFlags { public bool hazards, zones; }
        [Serializable] class Summary
        {
            public bool satisfied;
            public int steps, accepted_steps;
            public string stop_reason;
            public PhysicsReport unity;
        }

        string instruction = "Make the route longer while keeping the key before the exit and the three hazard zones.";
        string structuredJson = "{\n  \"schema_version\": 1,\n  \"domain\": \"keydoor\",\n  \"instruction\": \"Create a winding route.\",\n  \"targets\": {\"min_path_length\": 32, \"max_path_length\": 45, \"hazard_count\": 3, \"zone_hazards\": [0, 1, 2]}\n}";
        int minPath = 24, maxPath = 36, hazards = 3, left = 0, middle = 1, right = 2, maxSteps = 4;
        bool constrainHazards = true, constrainZones = true, visible = true, settings;
        int mode;
        Vector2 scroll;
        string projectRoot, python, status = "Adjust targets, then generate. Only numeric targets are verified.";
        string outputDirectory, preparedFile, operation, log = "";
        Process process;
        double started, nextPoll;
        readonly ConcurrentQueue<string> messages = new ConcurrentQueue<string>();
        LevelData currentLevel;
        PlayerMotor currentPlayer;

        public void SetLevel(LevelData level, PlayerMotor player)
        {
            currentLevel = level;
            currentPlayer = player;
            projectRoot = Application.isEditor
                ? Path.GetFullPath(Path.Combine(Application.dataPath, "../.."))
                : Environment.GetEnvironmentVariable("AGENTIC_PCG_ROOT") ?? Directory.GetCurrentDirectory();
            python = File.Exists("/opt/homebrew/bin/python3") ? "/opt/homebrew/bin/python3" : "python3";
            LayoutCamera();
        }

        float PanelWidth => Mathf.Min(370, Screen.width * .43f);

        void LayoutCamera()
        {
            if (currentPlayer == null) return;
            var camera = currentPlayer.transform.parent.GetComponentInChildren<Camera>();
            if (camera == null) return;
            float offset = visible ? (PanelWidth + 24) / Screen.width : 0;
            camera.rect = new Rect(offset, 0, 1 - offset, 1);
            camera.orthographicSize = Mathf.Max(currentLevel.Height / 2f + 1,
                currentLevel.Width / (2f * camera.aspect) + 1);
        }

        void Update()
        {
            LayoutCamera();
            while (messages.TryDequeue(out string message))
            {
                log += message + "\n";
                if (log.Length > 4000) log = log.Substring(log.Length - 4000);
            }
            if (process != null)
            {
                if (process.HasExited) Complete();
                else if (Time.realtimeSinceStartupAsDouble - started > maxSteps * 180 + 90)
                    Cancel("Generation timed out. Current map retained.");
            }
            if (string.IsNullOrEmpty(projectRoot) || Time.realtimeSinceStartupAsDouble < nextPoll) return;
            nextPoll = Time.realtimeSinceStartupAsDouble + .25;
            string root = Path.Combine(projectRoot, ".bridge");
            string jobs = Path.Combine(root, "jobs");
            if (!Directory.Exists(jobs)) return;
            // ponytail: one synchronous replay per tick; coroutine jobs if large maps cause long stalls.
            string file = Directory.GetFiles(jobs, "*.json").OrderBy(p => p).FirstOrDefault();
            if (file != null)
                try { BridgeFiles.Process(root, file); }
                catch (Exception error) { status = "Physics request failed: " + error.Message; }
        }

        void OnGUI()
        {
            var e = Event.current;
            if (process == null && e.type == EventType.KeyDown && (e.control || e.command) && e.keyCode == KeyCode.Return)
            {
                StartJob(e.shift ? "generate" : mode == 1 ? "validate" : "interpret");
                e.Use();
            }
            if (Event.current.type == EventType.MouseDown && Event.current.mousePosition.x > PanelWidth + 24)
                GUIUtility.keyboardControl = 0;
            bool canMove = process == null && (!visible || GUIUtility.keyboardControl == 0);
            if (currentPlayer != null)
            {
                if (currentPlayer.manualInput && !canMove) currentPlayer.body.linearVelocity = Vector2.zero;
                currentPlayer.manualInput = canMove;
            }
            if (GUI.Button(new Rect(10, 10, 125, 24), visible ? "Hide generation" : "Show generation"))
                visible = !visible;
            if (!visible) return;
            var previousColor = GUI.color;
            GUI.color = new Color(.08f, .10f, .15f);
            GUI.DrawTexture(new Rect(0, 40, PanelWidth + 24, Screen.height - 40), Texture2D.whiteTexture);
            GUI.color = previousColor;
            var wrap = new GUIStyle(GUI.skin.label) { wordWrap = true };
            var text = new GUIStyle(GUI.skin.textArea) { wordWrap = true };
            var box = new GUIStyle(GUI.skin.box) { wordWrap = true };
            GUILayout.BeginArea(new Rect(10, 44, PanelWidth, Mathf.Max(120, Screen.height - 54)), GUI.skin.box);
            scroll = GUILayout.BeginScrollView(scroll);
            GUILayout.Label("Agentic PCG", GUI.skin.box);
            GUILayout.Label("Domain: Key-door maze");
            GUILayout.Label("Click the map to play with WASD.");
            using (new GUIEnabled(process == null))
            {
                mode = GUILayout.Toolbar(mode, new[] { "Prompt + targets", "JSON" });
                if (mode == 0)
                {
                    GUILayout.Label("Instruction (any language)");
                    instruction = GUILayout.TextArea(instruction, text, GUILayout.MinHeight(65), GUILayout.Width(PanelWidth - 32));
                    if (GUILayout.Button("Interpret targets")) StartJob("interpret");
                    GUILayout.Label("Ctrl/Cmd+Enter: interpret (one model call).", wrap);
                    GUILayout.Space(5);
                    minPath = Knob("Min route steps", minPath, 128);
                    maxPath = Knob("Max route steps", maxPath, 128);
                    constrainHazards = GUILayout.Toggle(constrainHazards, "Target hazard count");
                    if (constrainHazards && !constrainZones) hazards = Knob("Hazards", hazards, 20);
                    constrainZones = GUILayout.Toggle(constrainZones, "Target left / middle / right hazards");
                    if (constrainZones)
                    {
                        left = Knob("Left", left, 10);
                        middle = Knob("Middle", middle, 10);
                        right = Knob("Right", right, 10);
                        if (constrainHazards) hazards = left + middle + right;
                    }
                    GUILayout.Label("Hazard total: " + (constrainZones ? (left + middle + right).ToString() : constrainHazards ? hazards.ToString() : "unconstrained"));
                    GUILayout.Label("Style guides the agent; controls set the verified targets.", wrap);
                }
                else
                {
                    structuredJson = GUILayout.TextArea(structuredJson, text, GUILayout.MinHeight(150), GUILayout.Width(PanelWidth - 32));
                    if (GUILayout.Button("Load JSON targets")) StartJob("validate");
                }
                maxSteps = Mathf.Clamp(Knob("Agent step budget", maxSteps, 8, 1), 1, 8);
                bool valid = mode == 1 || minPath <= maxPath;
                if (!valid) GUILayout.Label("Min route steps must not exceed max.");
                using (new GUIEnabled(valid))
                    if (GUILayout.Button("Generate + verify + load", GUILayout.Height(32))) StartJob("generate");
                GUILayout.Label("Ctrl/Cmd+Shift+Enter: generate.", wrap);
                settings = GUILayout.Toggle(settings, "Local Python settings");
                if (settings)
                {
                    GUILayout.Label("Repository folder (.env stays here)");
                    projectRoot = GUILayout.TextField(projectRoot ?? "");
                    GUILayout.Label("Python 3.10+ executable");
                    python = GUILayout.TextField(python ?? "python3");
                }
            }
            if (process != null && GUILayout.Button("Cancel; keep current map")) Cancel("Cancelled. Current map retained.");
            GUILayout.Space(6);
            GUILayout.Label(status, box, GUILayout.Width(PanelWidth - 32));
            if (!string.IsNullOrEmpty(outputDirectory)) GUILayout.Label("Run: " + Path.GetFileName(outputDirectory), wrap);
            if (settings && log.Length > 0) GUILayout.TextArea(log, text, GUILayout.Width(PanelWidth - 32));
            GUILayout.EndScrollView();
            GUILayout.EndArea();
        }

        static int Knob(string label, int value, int range, int minimum = 0)
        {
            GUILayout.BeginHorizontal();
            GUILayout.Label(label, GUILayout.Width(145));
            if (int.TryParse(GUILayout.TextField(value.ToString(), GUILayout.Width(55)), out int typed))
                value = Mathf.Clamp(typed, minimum, 8192);
            GUILayout.EndHorizontal();
            return Mathf.RoundToInt(GUILayout.HorizontalSlider(value, minimum, Mathf.Max(range, value)));
        }

        string RequestJson()
        {
            if (mode == 1) return structuredJson;
            var targets = new StringBuilder("{\"min_path_length\":").Append(minPath)
                .Append(",\"max_path_length\":").Append(maxPath);
            if (constrainHazards) targets.Append(",\"hazard_count\":").Append(constrainZones ? left + middle + right : hazards);
            if (constrainZones) targets.Append(",\"zone_hazards\":[").Append(left).Append(',').Append(middle).Append(',').Append(right).Append(']');
            targets.Append('}');
            string header = JsonUtility.ToJson(new RequestHeader { instruction = instruction });
            return header.Substring(0, header.Length - 1) + ",\"targets\":" + targets + "}";
        }

        void StartJob(string kind)
        {
            if (process != null) return;
            try
            {
                if (currentLevel == null || !File.Exists(Path.Combine(projectRoot, "unity_pcg", "cli.py")))
                    throw new ArgumentException("Set the repository folder in Local Python settings.");
                string id = Guid.NewGuid().ToString("N");
                string relative = ".bridge/requests/" + id;
                string directory = Path.Combine(projectRoot, relative);
                Directory.CreateDirectory(directory);
                File.WriteAllText(Path.Combine(directory, "input.json"), RequestJson());
                File.WriteAllText(Path.Combine(directory, "level.json"), JsonUtility.ToJson(currentLevel));
                preparedFile = Path.Combine(directory, "prepared.json");
                string arguments = "-u -m unity_pcg ";
                if (kind == "generate")
                {
                    string run = "runs/game-" + DateTime.Now.ToString("yyyyMMdd-HHmmss") + "-" + id.Substring(0, 8);
                    outputDirectory = Path.Combine(projectRoot, run);
                    arguments += "generate --request-file " + relative + "/input.json --level " + relative +
                        "/level.json --output " + run + " --backend unity --unity-project unity --timeout 120 --revise --max-steps " + maxSteps;
                }
                else arguments += "prepare-request --request-file " + relative + "/input.json --output " + relative +
                    "/prepared.json" + (kind == "interpret" ? " --interpret" : "");
                var info = new ProcessStartInfo(python, arguments)
                {
                    WorkingDirectory = projectRoot, UseShellExecute = false,
                    RedirectStandardOutput = true, RedirectStandardError = true, CreateNoWindow = true
                };
                info.EnvironmentVariables["UNITY_EDITOR_PATH"] = ""; // Use this running game's listener.
                info.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
                process = new Process { StartInfo = info };
                process.OutputDataReceived += (_, e) => { if (e.Data != null) messages.Enqueue(e.Data); };
                process.ErrorDataReceived += (_, e) => { if (e.Data != null) messages.Enqueue(e.Data); };
                process.Start();
                process.BeginOutputReadLine();
                process.BeginErrorReadLine();
                operation = kind;
                log = "";
                started = Time.realtimeSinceStartupAsDouble;
                status = kind == "generate" ? "Generating and testing candidates..." : "Preparing targets...";
                currentPlayer.manualInput = false;
                currentPlayer.body.linearVelocity = Vector2.zero;
            }
            catch (Exception error)
            {
                status = "Could not start: " + error.Message;
                StopProcess();
            }
        }

        void Complete()
        {
            // HasExited is already true; this flushes redirected output event handlers.
            process.WaitForExit();
            while (messages.TryDequeue(out string message)) log += message + "\n";
            int exit = process.ExitCode;
            try
            {
                if (operation != "generate")
                {
                    if (exit != 0) throw new InvalidOperationException("Request rejected. " + log);
                    var prepared = JsonUtility.FromJson<PreparedRequest>(File.ReadAllText(preparedFile));
                    var targets = prepared.request.targets;
                    instruction = prepared.request.instruction;
                    minPath = targets.min_path_length;
                    maxPath = targets.max_path_length;
                    constrainHazards = prepared.controls.hazards;
                    constrainZones = prepared.controls.zones;
                    hazards = targets.hazard_count;
                    if (constrainZones) { left = targets.zone_hazards[0]; middle = targets.zone_hazards[1]; right = targets.zone_hazards[2]; }
                    mode = 0;
                    status = "Targets loaded. Review the controls, then generate.";
                }
                else
                {
                    string summaryPath = Path.Combine(outputDirectory, "summary.json");
                    if (!File.Exists(summaryPath)) throw new InvalidOperationException("Generation failed. " + log);
                    var summary = JsonUtility.FromJson<Summary>(File.ReadAllText(summaryPath));
                    if (exit == 0 && summary.satisfied && summary.unity != null && summary.unity.won)
                    {
                        var level = JsonUtility.FromJson<LevelData>(File.ReadAllText(Path.Combine(outputDirectory, "final_level.json")));
                        level.Validate();
                        var nextPlayer = LevelBuilder.Build(level, gameObject.scene, true);
                        currentPlayer.transform.parent.gameObject.SetActive(false);
                        Destroy(currentPlayer.transform.parent.gameObject);
                        currentLevel = level;
                        currentPlayer = nextPlayer;
                        LayoutCamera();
                        GetComponent<LevelBootstrap>().levelJson = JsonUtility.ToJson(level);
                        status = "Verified map loaded. " + summary.accepted_steps + "/" + summary.steps +
                            " proposals saved; " + summary.unity.physics_steps + " physics steps.";
                    }
                    else status = "Current map retained: " + summary.stop_reason + ". " + log;
                }
            }
            catch (Exception error) { status = error.Message; }
            finally { StopProcess(); }
        }

        void Cancel(string reason)
        {
            StopProcess();
            status = reason;
        }

        void StopProcess()
        {
            if (process != null)
            {
                int pid = 0;
                try { pid = process.Id; if (!process.HasExited) { process.Kill(); process.WaitForExit(1000); } }
                catch (InvalidOperationException) { }
                process.Dispose();
                process = null;
                // Remove only this worker's pending jobs when Play stops or the user cancels.
                string jobs = Path.Combine(projectRoot, ".bridge", "jobs");
                if (pid != 0 && Directory.Exists(jobs))
                    foreach (string file in Directory.GetFiles(jobs, "*.json"))
                        try { if (JsonUtility.FromJson<BridgeJob>(File.ReadAllText(file)).owner_pid == pid) File.Delete(file); }
                        catch (IOException) { }
            }
            if (currentPlayer != null) currentPlayer.manualInput = true;
        }

        void OnDestroy() { StopProcess(); }

        struct GUIEnabled : IDisposable
        {
            readonly bool previous;
            public GUIEnabled(bool enabled) { previous = GUI.enabled; GUI.enabled = previous && enabled; }
            public void Dispose() { GUI.enabled = previous; }
        }
    }
}
