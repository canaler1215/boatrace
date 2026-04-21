"use client";
import { useRouter, useSearchParams } from "next/navigation";

interface Props {
  current: string; // YYYY-MM-DD
  today: string;   // YYYY-MM-DD
}

export function DateControl({ current, today }: Props) {
  const router = useRouter();
  const searchParams = useSearchParams();

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const params = new URLSearchParams(searchParams.toString());
    if (e.target.value && e.target.value !== today) {
      params.set("date", e.target.value);
    } else {
      params.delete("date");
    }
    router.push(`/dashboard?${params.toString()}`);
  }

  return (
    <div className="flex items-center gap-2 text-sm">
      <label htmlFor="race-date" className="text-gray-600">
        日付
      </label>
      <input
        id="race-date"
        type="date"
        value={current}
        max={today}
        onChange={handleChange}
        className="rounded border border-gray-300 bg-white px-2 py-1 text-sm focus:border-blue-500 focus:outline-none"
      />
      {current !== today && (
        <button
          onClick={() => {
            const params = new URLSearchParams(searchParams.toString());
            params.delete("date");
            router.push(`/dashboard?${params.toString()}`);
          }}
          className="text-xs text-blue-600 hover:underline"
        >
          今日に戻る
        </button>
      )}
    </div>
  );
}
