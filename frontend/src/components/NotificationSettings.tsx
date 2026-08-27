/* Notifications and installation, in Settings.
 *
 * The design brief for this panel is honesty. Push has five participants and four of them
 * belong to somebody else, so every state the user can land in has to be *named*:
 *
 *   - the server has no VAPID keys        -> say so; nothing the user does will help
 *   - the browser refused permission      -> say the app CANNOT ask again, and where to fix it
 *   - iOS, not installed                  -> say installation is the precondition
 *   - subscribed but nothing arrives      -> give them a button that proves the pipe
 *
 * A toggle that silently does nothing is worse than no toggle, and every one of those
 * states produces exactly that if it is not spelled out.
 */

import { useCallback, useEffect, useState } from "react";
import {
  Bell,
  BellRing,
  Clock,
  Download,
  Loader2,
  Sparkles,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { useInstallPrompt } from "@/hooks/useInstallPrompt";
import { useToast } from "@/hooks/useToast";
import * as api from "@/lib/api";
import type { JobRow, PushStatus } from "@/lib/api";
import * as push from "@/lib/push";

function JobList() {
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const toast = useToast();

  useEffect(() => {
    api
      .listJobs()
      .then(setJobs)
      .catch(() => {});
  }, []);

  const toggle = useCallback(
    async (job: JobRow, enabled: boolean) => {
      setBusy(job.name);
      // Optimistic: a switch that waits for a round trip feels broken.
      setJobs((rows) =>
        rows.map((r) => (r.name === job.name ? { ...r, enabled } : r)),
      );
      try {
        await api.setJobEnabled(job.name, enabled);
      } catch {
        setJobs((rows) =>
          rows.map((r) =>
            r.name === job.name ? { ...r, enabled: !enabled } : r,
          ),
        );
        toast.error("Couldn't change that");
      } finally {
        setBusy(null);
      }
    },
    [toast],
  );

  if (jobs.length === 0) return null;

  return (
    <ul className="mt-3 divide-y divide-border rounded-lg border border-border">
      {jobs.map((job) => (
        <li key={job.name} className="flex items-start gap-3 px-3 py-2.5">
          <div className="min-w-0 flex-1">
            <p className="flex items-center gap-1.5 text-sm font-medium">
              {job.description}
              {job.uses_ai && (
                <span
                  title="Uses a model, so it costs a little and counts towards your spend limit"
                  className="inline-flex items-center gap-0.5 rounded-full bg-accent px-1.5 py-0.5 text-[10px] font-normal text-accent-foreground"
                >
                  <Sparkles className="size-2.5" /> AI
                </span>
              )}
            </p>
            <p className="mt-0.5 flex items-center gap-1 text-xs text-muted-foreground">
              <Clock className="size-3" />
              {job.when}
              {job.last_status && (
                <span className="ml-1">
                  · last run{" "}
                  {job.last_status === "silent"
                    ? "nothing to report"
                    : job.last_status}
                </span>
              )}
            </p>
          </div>
          <Switch
            checked={job.enabled}
            disabled={busy === job.name}
            onCheckedChange={(v) => void toggle(job, v)}
            aria-label={job.description}
            className="mt-0.5"
          />
        </li>
      ))}
    </ul>
  );
}

export default function NotificationSettings() {
  const [status, setStatus] = useState<PushStatus | null>(null);
  const [subscribed, setSubscribed] = useState(false);
  const [working, setWorking] = useState(false);
  const [testing, setTesting] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const install = useInstallPrompt();
  const toast = useToast();

  const refresh = useCallback(() => {
    api
      .getPushStatus()
      .then(setStatus)
      .catch(() => {});
    push.hasSubscription().then(setSubscribed);
  }, []);

  useEffect(refresh, [refresh]);

  const blocked = push.pushBlockedReason();
  const permission = push.permission();

  async function enable() {
    if (!status) return;
    setWorking(true);
    setNote(null);
    const result = await push.subscribe(status.public_key);
    setWorking(false);
    if (result.ok) {
      setSubscribed(true);
      refresh();
      toast.success("Notifications are on");
    } else {
      setNote(result.reason);
    }
  }

  async function disable() {
    setWorking(true);
    await push.unsubscribe();
    setWorking(false);
    setSubscribed(false);
    refresh();
  }

  async function test() {
    setTesting(true);
    setNote(null);
    const result = await api.sendTestNotification();
    setTesting(false);
    if (result.ok) toast.success("Sent — it should appear in a moment");
    else setNote(result.reason ?? "It could not be sent.");
  }

  return (
    <>
      <section className="mt-4 rounded-xl border border-border p-4">
        <h2 className="mb-1 flex items-center gap-2 font-medium">
          <Bell className="size-4 text-muted-foreground" /> Notifications
        </h2>
        <p className="text-sm text-muted-foreground">
          Acero can tell you when something needs you, even when the app is
          closed. Everything it says is kept in the bell at the top, whether or
          not it reaches this device.
        </p>

        {status && !status.configured ? (
          <p className="mt-3 rounded-lg bg-secondary px-3 py-2 text-sm text-muted-foreground">
            This server has no notification keys configured, so nothing can be
            sent to a device yet. Notifications are still recorded and readable
            in the app.
          </p>
        ) : blocked ? (
          <p className="mt-3 rounded-lg bg-secondary px-3 py-2 text-sm text-muted-foreground">
            {blocked}
          </p>
        ) : permission === "denied" ? (
          <p className="mt-3 rounded-lg bg-secondary px-3 py-2 text-sm text-muted-foreground">
            Notifications are blocked for this site. Acero cannot ask again —
            you can re-allow them in your browser&rsquo;s site settings for this
            page.
          </p>
        ) : (
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Button onClick={subscribed ? disable : enable} disabled={working}>
              {working ? (
                <Loader2 className="size-4 animate-spin" />
              ) : subscribed ? (
                "Turn off on this device"
              ) : (
                <>
                  <BellRing className="size-4" /> Turn on for this device
                </>
              )}
            </Button>
            {subscribed && (
              <Button variant="outline" onClick={test} disabled={testing}>
                {testing ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  "Send a test"
                )}
              </Button>
            )}
            {status && status.devices > 0 && (
              <span className="text-xs text-muted-foreground">
                {status.devices} device{status.devices === 1 ? "" : "s"}{" "}
                registered
                {/* A readout, not a limit. There is no ceiling any more: volume is governed
                    by the nature of the subject — a measurement is reported when it crosses
                    a band, work you still have to do repeats until you do it — rather than
                    by cutting you off after a fixed count, which used to discard the overdue
                    nudge first. Counts DELIVERIES, not rows: one overdue record reminded
                    about six times counts six. Clearing the panel does not reset it. */}
                {status.pushed_today > 0 && (
                  <> · {status.pushed_today} sent today</>
                )}
              </span>
            )}
          </div>
        )}

        {note && (
          <p className="mt-2 rounded-lg bg-secondary px-3 py-2 text-sm text-muted-foreground">
            {note}
          </p>
        )}

        <h3 className="mt-5 text-sm font-medium">What Acero does on its own</h3>
        <p className="mt-1 text-xs text-muted-foreground">
          Turning one off stops it running at all — it is not just silenced.
        </p>
        <JobList />
      </section>

      {!install.installed && (install.canPrompt || install.manualSteps) && (
        <section className="mt-4 rounded-xl border border-border p-4">
          <h2 className="mb-1 flex items-center gap-2 font-medium">
            <Download className="size-4 text-muted-foreground" /> Install Acero
          </h2>
          <p className="text-sm text-muted-foreground">
            Adds Acero to your home screen, opening in its own window without
            browser controls.
          </p>
          {install.canPrompt ? (
            <Button className="mt-3" onClick={() => void install.install()}>
              Install
            </Button>
          ) : (
            <p className="mt-3 rounded-lg bg-secondary px-3 py-2 text-sm text-muted-foreground">
              {install.manualSteps}
            </p>
          )}
        </section>
      )}
    </>
  );
}
