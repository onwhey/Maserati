import { AlertTriangle } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function ApiError({ reason, message }: { reason: string; message?: string }) {
  return (
    <Card className="border-red-200 bg-red-50">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-red-700">
          <AlertTriangle className="h-4 w-4" />
          查询失败
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-1 text-sm text-red-700">
        <div>原因：{reason}</div>
        {message ? <div>说明：{message}</div> : null}
      </CardContent>
    </Card>
  );
}
