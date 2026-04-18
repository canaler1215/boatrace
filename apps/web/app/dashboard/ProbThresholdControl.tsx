"use client";
import { useRouter } from "next/navigation";

const PRESET_OPTIONS = [
  { value: 2, label: "2%" },
  { value: 3, label: "3%" },
  { value: 5, label: "5%" },
  { value: 7, label: "7%（推奨）" },
  { value: 10, label: "10%" },
  { value: 15, label: "15%" },
  { value: 20, label: "20%" },
  { value: 30, label: "30%" },
];

interface Props {
  current: number; // percentage, e.g. 7 for 7%
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
        {PRESET_OPTIONS.map((opt) => (
          <option key={opt.value} value={String(opt.value)}>
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  );
}
