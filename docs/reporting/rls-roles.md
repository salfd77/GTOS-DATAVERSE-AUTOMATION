# Row-Level Security roles (GTOS governance-aligned)

RLS is enforced at the semantic model, so it protects every downstream report and
app. Do **not** rely on hiding pages for security.

## Concept
GTOS carries authority/ownership in `gtos_governance` (`gtos_ownership`,
`gtos_authorityscope`, `gtos_approvedby`). Filter facts through their governance/
ownership so a viewer only sees rows within their authority scope.

## Role 1 — Owner sees own governance records
On table `gtos_governance`, table filter DAX:
```dax
[gtos_ownership] = USERPRINCIPALNAME()
```
This flows to `gtos_audit` via the `gtos_audit -> gtos_governance` relationship
(audit rows follow their governance record).

## Role 2 — Finding owner sees own findings
On table `gtos_finding`, table filter DAX:
```dax
[gtos_owner] = USERPRINCIPALNAME()
```
Use when finding ownership is stored as the viewer's UPN. If `gtos_owner` holds a
display name or team instead, map it via a small bridge table:
```dax
[gtos_owner] = LOOKUPVALUE ( UserMap[OwnerName], UserMap[UPN], USERPRINCIPALNAME() )
```

## Role 3 — Leadership (read-all)
No table filters. Assign to leadership/audit reviewers who must see everything.

## Validate before publishing
1. Model view -> **Manage roles** -> create the roles above.
2. **View as** -> pick a role (optionally with a specific UPN) -> confirm rows filter.
3. After publishing, assign Entra users/groups to each role in the workspace/app.

## Notes
- Ownership storage varies (UPN vs display name vs team). Confirm how `gtos_ownership`
  / `gtos_owner` are populated, then pick the matching filter form above.
- Keep the bridge table (if used) out of report visuals; it is a security artifact.
