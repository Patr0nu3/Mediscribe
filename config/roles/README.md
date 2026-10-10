# Speaker roles

[clinical.json](clinical.json) is the default role profile. It supplies the
automatic assignment rules and the editor's speaker choices.

Edit it directly, or copy it to another JSON file and select that file in `.env`:

```dotenv
MEDISCRIBE_ROLES_CONFIG=config/roles/custom.json
```

Restart the editor after changes.

| Field | What to edit |
|-------|--------------|
| `roles` | A list of entries with `name`, `aliases`, and `description` |
| `instructions` | Additional rules for automatic assignment |
| `required_roles` | Labels expected in every recording, or `[]` |
| `ordered_roles` | Labels for similar participants in order of first appearance, or `[]` |

When renaming a role, update its references in `required_roles`, `ordered_roles`,
and any aliases that need to change. `Unknown` is added automatically. Names must be unique and
contain no colon or line break.

Each role uses the same three fields. `aliases` lists alternate names, or `[]`.
`description` explains when to assign the role.

A minimal profile:

```json
{
  "roles": [
    {
      "name": "Interviewer",
      "aliases": ["host"],
      "description": "The person asking questions."
    },
    {
      "name": "Participant",
      "aliases": [],
      "description": "The person describing their experience."
    }
  ],
  "instructions": "Assign roles from the interview content."
}
```
