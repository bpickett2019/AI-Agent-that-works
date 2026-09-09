# Registration capability mapping — September 9, 2026

This is a source-level safety/capability checkpoint. The new inspection has not
run against staging yet and is not write acceptance.

## Authoritative scope findings

Cvent's public **Adding and Managing Registration Types** documentation says:

- registration types begin as Contact Types;
- changing a registration type name requires editing the corresponding Contact
  Type in Admin;
- an existing Contact Type becomes an event registration type when it is added
  to that event with **Add from Contact Types**;
- **Create Contact Type** creates a new contact and registration type.

Source: `https://support.cvent.com/s/communityarticle/Adding-Registration-Types`
(read September 9, 2026).

Consequences for this job:

1. The seven literal pipe-spacing name differences are not safe event-local
   name edits. Admin/shared Contact Type mutation is prohibited. The trusted
   registration mission now reports those fields as `PROHIBITED` instead of
   opening an event detail editor and searching for a Name input. Hidden
   `#Name` remains evidence only and is never a mutation target.
2. Missing SPONCOMP may be resolved only if the event's **Add from Contact
   Types** inventory contains one unique exact `SPONCOMP` Code row with the
   expected literal name. Adding that already-existing definition to the event
   would be event-local association. **Create Contact Type** is a shared
   definition operation and remains prohibited. No association implementation
   or SPONCOMP write is claimed yet.
3. There is no proven event-local registration-name creation capability.

Cvent's public **Setting Up Sponsorships** documentation places Group
Registration Settings on each registration path in Site Designer, not on a
registration-type detail page.

Source: `https://support.cvent.com/s/communityarticle/Setting-Up-Sponsorships-with-Flex`
(read September 9, 2026).

The RR asks whether each registration type can register another person, but the
compiled registration-path domain currently contains no type-to-path records
for this workbook. The trusted registration-type mission therefore retains Y/N
as a field-level hold and does not guess a path, change Site Designer, or search
the registration-type detail for a group control.

The RR column `ACTIVATE / NOT NEEDED` is used by the compiler to include rows;
its accepted values for this job are `ACTIVATE` and `REQUIRED`. Cvent's separate
**Open for registration** setting controls whether a registration type can
currently be selected. No evidence establishes that the RR inclusion directive
is an instruction to change that setting. The trusted projection now preserves
`activationDirective` as an enum instead of coercing it to an `active` boolean.
Exact event Code-row presence proves the requested association exists; Open for
registration is read back separately as an observation and is not mutated from
this directive.

## Fixed read-only capability inspection

`inspectRegistrationTypeCapabilities` is application-owned and operator-only;
it is not added to Pi's browser operation enum. It:

- accepts only independently compiled exact code/name identities;
- navigates only exact-key event-local routes;
- inventories the event's exact Code rows;
- opens one existing detail editor solely to inventory visible controls;
- opens the registration association editor and **Add from Contact Types**
  chooser solely to inventory exact candidates;
- never fills, checks, selects, adds, creates, saves, or invokes a configuration
  procedure;
- navigates away from untouched editors and reports
  `configurationWrites: 0`, `saveCalls: 0`.

The read-only runtime gateway explicitly allows this one fixed inspection while
continuing to reject generic clicks and every trusted write procedure. The
operator reader now records `registration-capability-readback.json` and accepts
the exact authorized event's observed lifecycle status for inspection, including
Completed; that does not waive write eligibility.

## Other safety correction

Fresh auth can now recognize `https://events.app.cvent.com/events/home` only
when HTTPS is clean and its event query key exactly equals the runtime's
server-authorized key. Profile, USER 1, organization-cookie, UI, and login-page
checks remain mandatory. Other modern-origin keys and all non-Cvent origins fail
closed.

## Still blocked

- Original ATTED mutation uncertainty is retained; no automatic retry or marker
  clearing is authorized.
- No staging capability readback has yet proved that SPONCOMP is available in
  Add from Contact Types.
- No SPONCOMP association, admission-item write, pricing write, Save, publish,
  communication, attendee/contact operation, or shared-definition change is
  performed by these source changes.
- Pricing's 24 combinations / 72 values still require a separate trusted
  editor/readback implementation. Public documentation alone is not sufficient
  to authorize selectors or writes against the live planner SPA.
