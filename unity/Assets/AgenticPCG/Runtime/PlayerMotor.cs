using UnityEngine;

namespace AgenticPCG
{
    // One controller and contact policy for human play and physics replay.
    public class PlayerMotor : MonoBehaviour
    {
        public Rigidbody2D body;
        public Collider2D playerCollider, keyCollider, doorCollider;
        public Collider2D[] hazards, walls;
        public bool hasKey, won, dead;
        public bool manualInput = true;
        public int wallContacts;
        public const float Speed = 4f;
        Vector2 input;

        void Update()
        {
            if (!manualInput) return;
            input = new Vector2(
                (Input.GetKey(KeyCode.D) || Input.GetKey(KeyCode.RightArrow) ? 1 : 0) -
                (Input.GetKey(KeyCode.A) || Input.GetKey(KeyCode.LeftArrow) ? 1 : 0),
                (Input.GetKey(KeyCode.W) || Input.GetKey(KeyCode.UpArrow) ? 1 : 0) -
                (Input.GetKey(KeyCode.S) || Input.GetKey(KeyCode.DownArrow) ? 1 : 0));
        }

        void FixedUpdate()
        {
            if (!manualInput || body == null) return;
            ObserveContacts();  // Contacts from the previous fixed physics step.
            Drive(input, Time.fixedDeltaTime);
        }

        public void Drive(Vector2 direction, float dt)
        {
            var movement = won || dead ? Vector2.zero : Vector2.ClampMagnitude(direction, 1f) * Speed * dt;
            body.MovePosition(body.position + movement);
        }

        public void ObserveContacts()
        {
            if (dead || won) return;
            foreach (var hazard in hazards)
                if (playerCollider.IsTouching(hazard)) { dead = true; return; }
            if (!hasKey && playerCollider.IsTouching(keyCollider))
            {
                hasKey = true;
                keyCollider.gameObject.SetActive(false);
                doorCollider.isTrigger = true;  // A locked door is solid until the key is collected.
            }
            if (hasKey && playerCollider.IsTouching(doorCollider)) won = true;
            foreach (var wall in walls)
                if (playerCollider.IsTouching(wall)) wallContacts++;
        }

        void OnGUI()
        {
            if (!manualInput) return;
            var camera = transform.parent.GetComponentInChildren<Camera>();
            float x = camera == null ? 10 : camera.pixelRect.x + 8;
            float width = camera == null ? Screen.width - 20 : camera.pixelRect.width - 16;
            GUI.Box(new Rect(x, 10, width, 65),
                "WASD / arrows | Collect key → exit | Bats are lethal\n" +
                (won ? "Won! Exit Play mode to edit or restart." : dead ? "Hazard hit. Restart Play mode." : hasKey ? "Key collected. Find the exit." : "Find the key first."));
        }
    }
}
