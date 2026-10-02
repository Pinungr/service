const labels: Record<string, string> = {
  unknown: 'Unknown / requires verification',
  under_warranty: 'Under warranty',
  out_of_warranty: 'Out of warranty',
  shop_warranty: 'Shop warranty',
};

export function warrantyLabel(value: string): string {
  return labels[value.toLowerCase()] ?? value.replace(/_/g, ' ');
}
