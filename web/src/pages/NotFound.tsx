import { Link } from "react-router-dom";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-[420px] py-24 text-center">
      <h1 className="text-lg font-semibold">Page not found</h1>
      <p className="mt-2 text-sm text-ink-2">The link may be out of date, or the run was deleted.</p>
      <Link to="/" className="mt-4 inline-block text-sm font-medium text-accent hover:underline">
        Go to runs
      </Link>
    </div>
  );
}
