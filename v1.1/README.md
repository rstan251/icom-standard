# ICOM v1.3 expander

Deterministic shorthand expander and autoNAK for ICOM, a one-line agent-to-agent message format.
By Robert Stanley / Iron Noodle Technologies. MIT License.

- Expands v1.1 shorthand (phrase shortcuts, implied header) to canonical v1 lines.
- Rejects anything it cannot expand with a single NAK line. It never guesses.
- Loads an **external** codebook (YAML or JSON) by path and can pin its version and sha256 prefix.
- `icom_noecho.py` is the rule-18 reference (quiet-verb reply ban, relay suppress, backlog collapse, unique DONE metrics).
- No network calls, no model calls. Python 3 standard library only; PyYAML is needed only for YAML codebooks.

Engine **1.3.0**. Parses `CO.CLIENT` (Rule 14a) and still accepts bare legacy lane codes. No production codebook ships here. `fixtures/codebook-fixture.json` is a made-up test fixture. `fixtures/clients-fixture.json` is a fake private registry (`id: 0000`, `short: ABC`).

## Run
```
python3 icom_expand.py --codebook fixtures/codebook-fixture.json "@LEAD>DEV #0a1b2c3d GO ops.deploy"
# -> @LEAD>ICOM>DEV P2 INT0 #iro-0a1b2c3d GO ops.deploy
python3 icom_expand.py --codebook fixtures/codebook-fixture.json "@LEAD>ICOM>OPS P1 CM.ABC #iro-0a1b2c3d ASK pr.voice.intake~cfg"
# -> @LEAD>ICOM>OPS P1 CM.ABC #iro-0a1b2c3d ASK pr.voice.intake~cfg
python3 icom_expand.py --codebook fixtures/codebook-fixture.json --clients fixtures/clients-fixture.json \
  "@LEAD>ICOM>EXT P1 CM.ABC #iro-0a1b2c3d ASK pr.voice.intake~cfg co=cogent-marketing cl=abc topic=voice-intake-config icx=1.2.0"
python3 icom_expand.py --codebook fixtures/codebook-fixture.json "@LEAD>DEV #0a1b2c3d \$RERUN-GO cb=9.9.9-fixture"
python3 tests/test_icom_expand.py      # plain asserts, prints TOTAL/PASS/FAIL
python3 tests/test_no_echo.py          # rule 18 vectors, prints TOTAL/PASS/FAIL
python3 scrub_check.py                 # export hygiene, expect hits=0
```
Exit codes: 0 = all lines OK, 1 = one or more NAKs, 2 = codebook load or pin error.

See SPEC.md for the grammar and no-echo rules. Layered codebooks and the conflict checker are planned for v1.1.1.
