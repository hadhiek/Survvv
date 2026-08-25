"use client";

import { FormEvent, useEffect, useState } from "react";
import { isDemoMode, supabase } from "../lib/supabase";

const api = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type Profile = {
  email: string;
  department: string;
  year: number;
  gender: string;
  available_credits: number;
  role: string;
};

type H = Record<string, string>;

const demo: H = {
  "X-Demo-User": process.env.NEXT_PUBLIC_DEMO_USER || "demo-student-1",
  "X-Demo-Email":
    process.env.NEXT_PUBLIC_DEMO_EMAIL || "student@nitc.ac.in",
};

async function me(headers: H) {
  const r = await fetch(`${api}/me`, { headers });
  const d = await r.json();

  if (!r.ok) {
    throw Error(d.detail || "Could not reach your account.");
  }

  return d as Profile;
}

export default function Home() {
  const [p, setP] = useState<Profile | null>(null);
  const [h, setH] = useState<H | null>(null);
  const [note, setNote] = useState("");
  const [ready, setReady] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        if (isDemoMode) {
          setH(demo);
          setP(await me(demo));
        } else {
          const {
            data: { session },
          } = await supabase!.auth.getSession();

          if (session) {
            const x = {
              Authorization: `Bearer ${session.access_token}`,
            };

            setH(x);
            setP(await me(x));
          }
        }
      } catch (e) {
        setNote(
          e instanceof Error ? e.message : "Unable to load account."
        );
      } finally {
        setReady(true);
      }
    })();

    if (!supabase) return;

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange(async (_, s) => {
      if (!s) {
        setH(null);
        setP(null);
        return;
      }

      try {
        const x = {
          Authorization: `Bearer ${s.access_token}`,
        };

        setH(x);
        setP(await me(x));
      } catch (e) {
        setNote(
          e instanceof Error ? e.message : "Unable to load account."
        );
      }
    });

    return () => subscription.unsubscribe();
  }, []);

  if (!ready) {
    return (
      <main>
        <p className="empty">Loading…</p>
      </main>
    );
  }

  if (!h) {
    return <Login note={note} setNote={setNote} />;
  }

  if (!p || p.department === "Unspecified") {
    return (
      <ProfileForm
        headers={h}
        done={setP}
        note={note}
        setNote={setNote}
      />
    );
  }

  return (
    <Dashboard
      profile={p}
      headers={h}
      note={note}
      signOut={async () => {
        if (!isDemoMode) {
          await supabase!.auth.signOut();
        }

        setP(null);
        setH(null);
      }}
    />
  );
}

function Login({
  note,
  setNote,
}: {
  note: string;
  setNote: (s: string) => void;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  async function go(e: FormEvent, signup: boolean) {
    e.preventDefault();
    setBusy(true);
    setNote("");

    if (!email.toLowerCase().endsWith("@nitc.ac.in")) {
      setNote("Use an @nitc.ac.in address.");
      setBusy(false);
      return;
    }

    const { error } = signup
      ? await supabase!.auth.signUp({
          email,
          password,
          options: {
            emailRedirectTo: window.location.origin,
          },
        })
      : await supabase!.auth.signInWithPassword({
          email,
          password,
        });

    if (error) {
      setNote(error.message);
    } else if (signup) {
      setNote(
        "Check your NITC inbox, verify your email, then sign in."
      );
    }

    setBusy(false);
  }

  return (
    <main>
      <header>
        <div className="logo">
          NITC <span>Survey Exchange</span>
        </div>
      </header>

      <section className="auth card">
        <h1>Welcome</h1>

        <p className="meta">
          Sign in with your verified NITC account.
        </p>

        {note && <p className="notice">{note}</p>}

        <form>
          <label>
            Email
            <input
              type="email"
              placeholder="you@nitc.ac.in"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </label>

          <label>
            Password
            <input
              type="password"
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </label>

          <div className="actions">
            <button
              disabled={busy}
              onClick={(e) => go(e, false)}
            >
              Sign in
            </button>

            <button
              disabled={busy}
              className="secondary"
              onClick={(e) => go(e, true)}
            >
              Create account
            </button>
          </div>
        </form>
      </section>
    </main>
  );
}

function ProfileForm({
  headers,
  done,
  note,
  setNote,
}: {
  headers: H;
  done: (p: Profile) => void;
  note: string;
  setNote: (s: string) => void;
}) {
  const [f, setF] = useState({
    roll_number: "",
    gender: "",
    program: "B.Tech",
    batch: "2024",
    department: "",
    year: "1",
  });

  async function save(e: FormEvent) {
    e.preventDefault();
    setNote("");

    const r = await fetch(`${api}/me`, {
      method: "PUT",
      headers: {
        ...headers,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        ...f,
        batch: Number(f.batch),
        year: Number(f.year),
      }),
    });

    const d = await r.json();

    if (!r.ok) {
      setNote(d.detail || "Could not save profile.");
      return;
    }

    done(await me(headers));
  }

  return (
    <main>
      <header>
        <div className="logo">
          NITC <span>Survey Exchange</span>
        </div>
      </header>

      <section className="auth card">
        <h1>Complete your profile</h1>

        <p className="meta">
          Used only for matching quota groups.
        </p>

        {note && <p className="notice">{note}</p>}

        <form onSubmit={save}>
          <label>
            Roll number
            <input
              required
              value={f.roll_number}
              onChange={(e) =>
                setF({ ...f, roll_number: e.target.value })
              }
            />
          </label>

          <label>
            Department
            <input
              required
              placeholder="CSE"
              value={f.department}
              onChange={(e) =>
                setF({ ...f, department: e.target.value })
              }
            />
          </label>

          <label>
            Program
            <input
              required
              value={f.program}
              onChange={(e) =>
                setF({ ...f, program: e.target.value })
              }
            />
          </label>

          <label>
            Batch
            <input
              required
              type="number"
              value={f.batch}
              onChange={(e) =>
                setF({ ...f, batch: e.target.value })
              }
            />
          </label>

          <label>
            Year
            <input
              required
              min="1"
              max="8"
              type="number"
              value={f.year}
              onChange={(e) =>
                setF({ ...f, year: e.target.value })
              }
            />
          </label>

          <label>
            Gender
            <select
              required
              value={f.gender}
              onChange={(e) =>
                setF({ ...f, gender: e.target.value })
              }
            >
              <option value="">Select</option>
              <option>Male</option>
              <option>Female</option>
              <option>Other</option>
              <option>Prefer not to say</option>
            </select>
          </label>

          <button type="submit">Save profile</button>
        </form>
      </section>
    </main>
  );
}

function Dashboard({
  profile,
  headers,
  note,
  signOut,
}: {
  profile: Profile;
  headers: H;
  note: string;
  signOut: () => void;
}) {
  const [s, setS] = useState<any[]>([]);
  const [message, setMessage] = useState(note);

  useEffect(() => {
    fetch(`${api}/surveys/feed`, { headers })
      .then(async (r) => {
        const d = await r.json();

        if (!r.ok) {
          throw Error(
            d.detail || "Could not load surveys."
          );
        }

        return d;
      })
      .then(setS)
      .catch((e) => setMessage(e.message));
  }, [headers]);

  return (
    <main>
      <header>
        <div className="logo">
          NITC <span>Survey Exchange</span>
        </div>

        <div>
          <span className="balance">
            {profile.available_credits} credits
          </span>

          <button
            className="secondary signout"
            onClick={signOut}
          >
            Sign out
          </button>
        </div>
      </header>

      <section className="hero">
        <h1>
          Help research. Earn credits. Reach the right
          respondents.
        </h1>

        <p>
          {profile.department} · Year {profile.year} ·{" "}
          {profile.gender}
        </p>
      </section>

      <div className="grid">
        <section>
          <h2>Available surveys</h2>

          {message && (
            <p className="notice">{message}</p>
          )}

          {s.length === 0 ? (
            <p className="empty">
              No open surveys match your demographic right now.
            </p>
          ) : (
            s.map((x) => (
              <article className="card" key={x.id}>
                <h3>{x.title}</h3>
                <p>{x.description}</p>
                <p className="reward">
                  +{x.reward} credits
                </p>
              </article>
            ))
          )}
        </section>

        <aside>
          <div className="card">
            <h2>How it works</h2>
            <p>1. Complete a verified survey.</p>
            <p>2. Earn credits.</p>
            <p>3. Spend them on your own survey.</p>
          </div>

          {profile.role === "ADMIN" && (
            <div className="notice">
              Administrator account active.
            </div>
          )}
        </aside>
      </div>
    </main>
  );
}