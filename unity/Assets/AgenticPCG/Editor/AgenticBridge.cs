using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;

namespace AgenticPCG.Editor
{
    [InitializeOnLoad]
    public static class AgenticBridge
    {
        static double nextPoll;
        static string Root => Path.GetFullPath(Path.Combine(Application.dataPath, "../../.bridge"));

        static AgenticBridge() { EditorApplication.update += Poll; }

        static void Poll()
        {
            if (Application.isBatchMode || EditorApplication.isPlayingOrWillChangePlaymode ||
                EditorApplication.isCompiling || EditorApplication.timeSinceStartup < nextPoll) return;
            nextPoll = EditorApplication.timeSinceStartup + .25;
            string jobs = Path.Combine(Root, "jobs");
            if (!Directory.Exists(jobs)) return;
            // ponytail: one synchronous job per tick; use async Play Mode jobs if scene tests get longer.
            string file = Directory.GetFiles(jobs, "*.json").OrderBy(p => p).FirstOrDefault();
            if (file != null)
            {
                try { BridgeFiles.Process(Root, file); }
                catch (Exception error) { Debug.LogError("Agentic PCG bridge: " + error.Message); }
            }
        }

        public static void Batch()
        {
            string[] args = Environment.GetCommandLineArgs();
            int index = Array.IndexOf(args, "-pcgJob");
            if (index < 0 || index + 1 >= args.Length) throw new ArgumentException("Missing -pcgJob");
            var result = BridgeFiles.Process(Root, args[index + 1]);
            if (!result.won) EditorApplication.Exit(2);
        }

    }
}
