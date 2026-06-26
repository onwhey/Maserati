import { loginAction } from "@/app/login/actions";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

export function LoginForm({
  next,
  message,
  className
}: {
  next: string;
  message?: string;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-6", className)}>
      <Card>
        <CardHeader className="p-6">
          <CardTitle className="text-2xl">Login to your account</CardTitle>
          <CardDescription></CardDescription>
        </CardHeader>
        <CardContent className="p-6 pt-0">
          <form action={loginAction}>
            <input type="hidden" name="next" value={next} />
            <div className="flex flex-col gap-6">
              {message ? (
                <div className="rounded-md border border-destructive/40 bg-destructive/15 px-3 py-2 text-sm text-destructive-foreground">
                  {message}
                </div>
              ) : null}
              <div className="grid gap-3">
                <Label htmlFor="username">Username</Label>
                <Input id="username" name="username" type="text" placeholder="" autoComplete="username" required />
              </div>
              <div className="grid gap-3">
                <div className="flex items-center">
                  <Label htmlFor="password">Password</Label>
                  
                </div>
                <Input id="password" name="password" type="password" autoComplete="current-password" required />
              </div>
              <div className="flex flex-col gap-3">
                <Button type="submit" className="w-full">
                  Login
                </Button>
            
              </div>
            </div>
            <div className="mt-4 text-center text-sm">
            
            
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
