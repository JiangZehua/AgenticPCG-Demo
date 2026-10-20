using System;
using System.Diagnostics;
#if UNITY_EDITOR
using UnityEditor.SceneManagement;
#endif
using UnityEngine;
using UnityEngine.SceneManagement;

namespace AgenticPCG
{
    public static class PhysicsReplay
    {
        public static PhysicsReport Run(BridgeJob job)
        {
            var report = new PhysicsReport { request_id = job.request_id, level_digest = job.level_digest,
                unity_version = Application.unityVersion,
                backend = Application.isPlaying ? "unity-physics-runtime" : "unity-physics-editmode" };
            var clock = Stopwatch.StartNew();
            Scene scene = default;
            var activeScene = SceneManager.GetActiveScene();
            int layer = -1;
            bool[] previousCollisionMask = null;
            const float dt = .02f;
            try
            {
                job.level.Validate();
                ValidateRoute(job);
                // Reserve an unused layer; Edit mode also needs a layer mask on the shared physics world.
                layer = FindUnusedPhysicsLayer();
                previousCollisionMask = new bool[32];
                for (int other = 0; other < 32; other++)
                {
                    previousCollisionMask[other] = Physics2D.GetIgnoreLayerCollision(layer, other);
                    Physics2D.IgnoreLayerCollision(layer, other, other != layer);
                }
                // Preview scenes also work when the user's current scene is untitled/unsaved.
                if (Application.isPlaying)
                    scene = SceneManager.CreateScene("PCG Test " + job.request_id,
                        new CreateSceneParameters(LocalPhysicsMode.Physics2D));
#if UNITY_EDITOR
                else scene = EditorSceneManager.NewPreviewScene();
#endif
                var player = LevelBuilder.Build(job.level, scene, false, layer);
                report.colliders = player.walls.Length + player.hazards.Length + 3;
                var physics = scene.GetPhysicsScene2D();
                Physics2D.SyncTransforms();
                foreach (var point in job.route)
                {
                    int budget = 100;
                    while (Vector2.Distance(player.body.position, point.World) > .025f && !player.won && !player.dead && budget-- > 0)
                    {
                        var delta = point.World - player.body.position;
                        player.Drive(Vector2.ClampMagnitude(delta / (PlayerMotor.Speed * dt), 1f), dt);
                        if (!physics.Simulate(dt, 1 << layer)) throw new InvalidOperationException("Physics simulation did not advance");
                        report.physics_steps++;
                        // Explicit observation gives Editor and runtime replay the same contact policy.
                        player.ObserveContacts();
                    }
                    if (player.dead) { report.error = "Hazard contact"; break; }
                    if (player.won) break;
                    if (budget <= 0) { report.error = $"Stuck at grid ({point.x},{point.y})"; break; }
                }
                report.won = player.won;
                report.has_key = player.hasKey;
                report.dead = player.dead;
                report.wall_contacts = player.wallContacts;
                if (!report.won && report.error == "") report.error = "Route ended without key-and-door contact";
                report.simulation_seconds = report.physics_steps * dt;
            }
            catch (Exception error) { report.error = error.Message; }
            finally
            {
                if (scene.IsValid())
                {
                    if (Application.isPlaying) SceneManager.UnloadSceneAsync(scene);
#if UNITY_EDITOR
                    else EditorSceneManager.ClosePreviewScene(scene);
#endif
                }
                if (previousCollisionMask != null)
                    for (int other = 0; other < 32; other++)
                        Physics2D.IgnoreLayerCollision(layer, other, previousCollisionMask[other]);
                if (activeScene.IsValid()) SceneManager.SetActiveScene(activeScene);
                report.evaluation_seconds = clock.Elapsed.TotalSeconds;
            }
            return report;
        }

        static int FindUnusedPhysicsLayer()
        {
            var used = new bool[32];
            foreach (var collider in Resources.FindObjectsOfTypeAll<Collider2D>())
                if (collider.gameObject.scene.IsValid()) used[collider.gameObject.layer] = true;
            foreach (var body in Resources.FindObjectsOfTypeAll<Rigidbody2D>())
                if (body.gameObject.scene.IsValid()) used[body.gameObject.layer] = true;
            for (int layer = 31; layer >= 8; layer--)
                if (!used[layer]) return layer;
            throw new InvalidOperationException("No unused user physics layer available for isolated replay");
        }

        static void ValidateRoute(BridgeJob job)
        {
            if (job.route == null || job.route.Length == 0 || job.route.Length > 8192)
                throw new ArgumentException("Route must have 1..8192 points");
            var previous = job.level.Position('P');
            bool hasKey = false;
            for (int i = 0; i < job.route.Length; i++)
            {
                var p = job.route[i];
                if (p.x < 0 || p.y < 0 || p.x >= job.level.Width || p.y >= job.level.Height)
                    throw new ArgumentException("Route coordinate out of bounds");
                if ((i == 0 && p.World != previous) || (i > 0 && (p.World - previous).sqrMagnitude != 1f))
                    throw new ArgumentException("Route must start at P and use cardinal unit steps");
                char tile = job.level.rows[p.y][p.x];
                if (tile == '#' || tile == 'H' || (tile == 'D' && !hasKey))
                    throw new ArgumentException("Route crosses an impassable tile");
                if (tile == 'K') hasKey = true;
                previous = p.World;
            }
            if (!hasKey || previous != job.level.Position('D'))
                throw new ArgumentException("Route must visit K then end at D");
        }
    }
}
