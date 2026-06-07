import Link from "next/link";

export default function DigestNotFound() {
  return (
    <main className="mx-auto max-w-3xl px-4 py-20 text-center">
      <h1 className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>
        Digest not found
      </h1>
      <p className="mt-2 text-sm" style={{ color: "var(--text-muted)" }}>
        That daily digest doesn&rsquo;t exist (yet).
      </p>
      <Link
        href="/digest"
        className="mt-6 inline-block text-sm font-semibold"
        style={{ color: "var(--accent)" }}
      >
        ← All digests
      </Link>
    </main>
  );
}
