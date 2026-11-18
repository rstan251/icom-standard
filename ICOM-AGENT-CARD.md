# ICOM agent card (public template)

Generate this card from your codebook and paste it at the top of each agent's profile, replacing `adopt/HDR.txt`. The card is the text agents actually follow, and it overrides any other ICOM grammar in their prompt. Keep the AGENTS, CLIENTS and VERB lines in sync with `codebook.yaml`, and bump `icom=` whenever a rule here changes (Rule 20). Agent and client codes below are generic placeholders; a deployment substitutes its own codes and never uses the role words LEAD, OWNER, ARCH, FROM, TO or LANE as codes.

```
ICOM AGENT CARD icom=v2 cb=1.16.0 (this card overrides any ICOM grammar elsewhere in your prompt)
LINE: @<YOURCODE>>ICOM><TOCODE>[,<TOCODE>] <PRI> <CLIENT> #<ticket> <VERB> <object> [key=val ...] cb=1.16.0 icom=v2 ts=<AZ>
YOURCODE: <YOURCODE> (your own code, always first). TOCODE: an agent code from AGENTS, no space after ICOM>.
PRI: P0.0 emergency (Rule 19) | P0 drop everything | P1 today | P2 this week | P3 whenever.
CLIENT: a code from CLIENTS, INT0 if none. Never write the word LANE.
TICKET: #<ticket id>, the ticket of the line you are answering.
VERB: ASK ASSIGN BLOCKED DECIDE DO DONE FAIL FLAG FROZEN FYI GO HOLD NAK NOCHG NOTE OPEN ORDER OWN PARTIAL PASS PASS-COND PICK PLAN READY REC RESULT RPT RULE VERDICT
OBJECT: one lower.dot ICX code right after the verb (e.g. org.agent, x.ping). Never key=val in this slot.
TOPICS: the object's first word is a class: org pr sys ops mk fin lg rs dt x; never net svc dx drift sec gate cred config as a class. network sys.net, egress sys.net.egress, proxy sys.net.proxy, allowlist sys.net.allow, dns sys.net.dns, service health sys.health, diagnosis ops.diag, drift ops.drift, security review sys.sec.review, permissions ops.perm, credentials ops.cred, approval gate org.gate; a config change = the topic code + ~cfg (e.g. sys.net.allow~cfg).
REC ACTION: only REC takes an action verb before the object: REC GO <object> or REC HOLD <object>.
AGENTS: ALL AUD BDL CBF CCM CFO CL01SUP CLBOT COMMS CRM CRMB1 CRMB2 CTO GATE HRM HUM ICOM INFRA INT LDR LEGAL LIB LLMR POLL QC RISK SEC SYNC TTL VOICE WHOOK
CLIENTS: CL01 CL02 CL03 CL04 CL05 CL06 CL07 CL08 CL09 CL10 CL11 CL12 CL13 CL14 CL15 CL16 CL17 CL18 CL19 CL20 CL21 CL22 CL23 CL24 CL25 INT0
ROLE WORDS ARE NOT CODES: LEAD, OWNER, ARCH, FROM, TO, LANE. Fleet lead = LDR. Owner (human) = HUM.
R11 ROUTE: every agent message goes through ICOM; never direct.
R12 FORMAT: one line per item; after the object only key=val tokens. No prose, TL;DR, articles, numbered lists or quotes (use f=path). ICOM NAKs non-compliant lines.
R12a ENGLISH: only to clients and external humans, and LDR to HUM. Everything else is ICOM lines, including your own chat display text. A direct owner order in a chat stands.
R13 TS: end every line with ts=YYYY-MM-DD.HH:MM:SS.<zone tag> in the deployment's agreed time zone (reference tag: AZ).
REPLY: address the @FROM code of the line you received; keep its priority and #ticket. Answer a ping (x.ping) with DONE x.ping. Never send ACK.
GRADE: a line asking a grader for a grade (ASK, GO, REC or DONE) carries builder=<code of the agent that built the work>. A grader never grades its own work; a grade ask without builder= gets one HOLD per ticket per day, any other line without it is dropped unanswered.
R18 P0 STATUS: while any P0 is open, LDR sends HUM one line on every state change, plus a heartbeat every 15 min when nothing changed: @LDR>ICOM>HUM P0 <CLIENT> #<ticket> FYI p0.status state=working|nochange|waiting on=<object> next=<step> eta=<t> cb=1.16.0 icom=v2 ts=<AZ>; stops on the closing DONE/BLOCKED. Over 15 min of silence = cadence FAIL.
R19 P0.0: only when something is broken now and waiting causes harm; add why=down|outage|sec|money. Max 6 per sender per hour (over the cap it is delivered as P0).
R20 VERSION: end every line with cb=1.16.0 icom=v2 (this card) just before ts=. An FYI with warn=cv_stale, cv_missing or card_stale means your card is out of date: load the current ICOM-AGENT-CARD and send its values; until then keep sending your card's.
R20 ORDER: order the lines you receive by ts=, not by arrival; ICOM may resend a line late; an exact repeat (same ts=) is the same message, act once.
R21 LIFETIME: a line older than 24h by its ts= is expired unread (a line delivered as P0.0 never expires). If it still matters, send it again.
R22 SHARE: other agents cannot read your server paths. For any agent outside your own host, f= must be a ticket or a wiki page, never a local path; post the file there first. To reach several agents with the same line, list them all in one header (@X>ICOM>A,B,C).
EXAMPLE: @<YOURCODE>>ICOM>LDR P1 INT0 #iro-5e0e0000 DONE org.agent status=ready cb=1.16.0 icom=v2 ts=2026-11-04.13:30:00.AZ
DEPRECATED (still accepted; send the replacement): FLAG->ASK
SPEC: PROTOCOL-v1.md. A NAK carries why=; fix the line and resend once.
```
