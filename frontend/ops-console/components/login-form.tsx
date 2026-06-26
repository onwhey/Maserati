import { loginAction } from "@/app/login/actions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

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
    <form action={loginAction} className={className}>
      <input type="hidden" name="next" value={next} />
      <div className="flex flex-col items-center gap-2 text-center">
        <h1 className="text-2xl font-bold">登录</h1>
      </div>
      {message ? (
        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {message}
        </div>
      ) : null}
      <div className="grid gap-2">
        <label className="text-sm font-medium" htmlFor="username">
          用户名
        </label>
        <Input id="username" name="username" autoComplete="username" required />
      </div>
      <div className="grid gap-2">
        <label className="text-sm font-medium" htmlFor="password">
          密码
        </label>
        <Input id="password" name="password" type="password" autoComplete="current-password" required />
      </div>
      <Button className="w-full" type="submit">
        登录
      </Button>
    </form>
  );
}
