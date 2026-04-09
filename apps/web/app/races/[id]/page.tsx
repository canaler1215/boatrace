interface Props {
  params: Promise<{ id: string }>;
}

export default async function RacePage({ params }: Props) {
  const { id } = await params;
  return (
    <div>
      <h2 className="mb-6 text-2xl font-bold">レース詳細</h2>
      <p className="text-gray-500">Race ID: {id}</p>
    </div>
  );
}
