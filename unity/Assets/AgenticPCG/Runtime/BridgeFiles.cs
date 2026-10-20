using System;
using System.IO;
using System.Linq;
using UnityEngine;

namespace AgenticPCG
{
    // Same file protocol for the Editor listener and the running desktop demo.
    public static class BridgeFiles
    {
        public static PhysicsReport Process(string root, string path)
        {
            string full = Path.GetFullPath(path);
            if (Path.GetDirectoryName(full) != Path.Combine(root, "jobs"))
                throw new ArgumentException("Job must be inside .bridge/jobs");
            if (new FileInfo(full).Length > 200000) throw new ArgumentException("Job too large");
            string name = Path.GetFileNameWithoutExtension(full);
            try
            {
                var job = JsonUtility.FromJson<BridgeJob>(File.ReadAllText(full));
                if (job == null || job.request_id != name || name.Length != 32 || !name.All(Uri.IsHexDigit) ||
                    job.level_digest == null || job.level_digest.Length != 64 || !job.level_digest.All(Uri.IsHexDigit))
                    throw new ArgumentException("Invalid job identity");
                var result = PhysicsReplay.Run(job);
                string directory = Path.Combine(root, "results");
                Directory.CreateDirectory(directory);
                string destination = Path.Combine(directory, name + ".json");
                string temporary = destination + ".tmp";
                File.WriteAllText(temporary, JsonUtility.ToJson(result, true));
                File.Move(temporary, destination);
                return result;
            }
            finally { File.Delete(full); }
        }
    }
}
