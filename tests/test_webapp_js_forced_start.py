"""A forced job start reports its refusal like any other start (#151).

The second click after a "busy" answer used to post /api/jobs/start with
force: true and throw the reply away, the one write #142 missed.
"""
from tests.js_harness import eval_js


def test_a_forced_start_sends_force_and_reports_a_refusal():
    got = eval_js("""(async () => {
      dom.reset();
      let sent = null;
      app.setFetch((url, opts) => {
        sent = JSON.parse(opts.body);
        return Promise.resolve({ok: false, status: 500,
          json: () => Promise.resolve({error: "the runner is stuck"})});
      });
      const result = await app.startTask("check", {}, true);
      return [sent, result, dom.writes["#task-message:text"]];
    })()""")
    assert got == [{"command": "check", "options": {}, "force": True},
                   "error", "the runner is stuck"]


def test_an_ordinary_start_sends_no_force():
    sent = eval_js("""(async () => {
      let sent = null;
      app.setFetch((url, opts) => { sent = JSON.parse(opts.body);
        return new Promise(() => {}); });
      app.startTask("check", {});
      await Promise.resolve();
      return sent;
    })()""")
    assert sent == {"command": "check", "options": {}}
