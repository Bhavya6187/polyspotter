import Link from "next/link";

export default function NotFound() {
  return (
    <main className="mx-auto max-w-2xl px-6 py-24 text-center">
      <h1 className="text-3xl font-semibold">Article not found</h1>
      <p className="mt-4 text-zinc-400">
        We couldn&apos;t find the article you were looking for.
      </p>
      <p className="mt-8">
        <Link href="/" className="text-indigo-400 hover:text-indigo-300 underline">
          Back to PolySpotter
        </Link>
      </p>
    </main>
  );
}
