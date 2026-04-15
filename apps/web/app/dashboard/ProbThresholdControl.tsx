"use client";
import { useRouter } from "next/navigation";

const PRESET_OPTIONS = [2, 3, 5, 10, 15, 20, 30];

interface Props {
  current: number; // percentage, e.g. 5 for 5%
}

export function ProbThresholdControl({ current }: Props) {
  const router = useRouter();

  function handleChange(e: React.ChangeEvent<HTMLSelectElement>) {
    router.push(`/dashboard?prob=${e.target.value}`);
  }

  return (
    <div className="flex items-center gap-2 text-sm">
      <label htmlFor="prob-threshold" className="text-gray-600">
        的中確率閾値
      </label>
      <select
        id="prob-threshold"
        value={String(current)}
        onChange={handleChange}
        className="rounded border border-gray-300 bg-white px-2 py-1 text-sm focus:border-blue-500 focus:outline-none"
      >
        {PRESET_OPTIONS.map((v) => (
          <option key={v} value={String(v)}>
            {v}%
          </option>
        ))}
      </select>
    </div>
  );
}
