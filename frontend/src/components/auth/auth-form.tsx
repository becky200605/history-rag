"use client";

import { AlertCircleIcon } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { startTransition, useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { authClient } from "@/server/better-auth/client";

type AuthMode = "login" | "register";

type LoginFormState = {
  email: string;
  password: string;
};

type RegisterFormState = {
  inviteCode: string;
  name: string;
  email: string;
  password: string;
};

const DEFAULT_LOGIN_FORM: LoginFormState = {
  email: "",
  password: "",
};

const DEFAULT_REGISTER_FORM: RegisterFormState = {
  inviteCode: "",
  name: "",
  email: "",
  password: "",
};

const INPUT_CLASS_NAME =
  "border-[rgba(57,130,152,0.18)] bg-[rgb(249,252,252)] text-[rgb(23,89,108)] placeholder:text-slate-400";

const PRIMARY_BUTTON_CLASS_NAME =
  "bg-[rgb(57,130,152)] text-white hover:bg-[rgb(49,113,132)]";

function resolveNextPath(nextPath: string | null) {
  if (nextPath?.startsWith("/") !== true) {
    return "/workspace";
  }
  return nextPath;
}

export function AuthForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [mode, setMode] = useState<AuthMode>("login");
  const [error, setError] = useState("");
  const [isPending, setIsPending] = useState(false);
  const [loginForm, setLoginForm] = useState(DEFAULT_LOGIN_FORM);
  const [registerForm, setRegisterForm] = useState(DEFAULT_REGISTER_FORM);
  const nextPath = resolveNextPath(searchParams.get("next"));

  const handleLogin = () => {
    const email = loginForm.email.trim();
    const password = loginForm.password;

    if (!email || !password) {
      setError("请输入邮箱和密码");
      return;
    }

    startTransition(async () => {
      setIsPending(true);
      setError("");

      const result = await authClient.signIn.email({
        email,
        password,
        rememberMe: true,
      });

      setIsPending(false);

      if (result.error) {
        setError(result.error.message ?? "登录失败，请稍后重试");
        return;
      }

      router.replace(nextPath);
      router.refresh();
    });
  };

  const handleRegister = () => {
    const inviteCode = registerForm.inviteCode.trim();
    const name = registerForm.name.trim();
    const email = registerForm.email.trim();
    const password = registerForm.password;

    if (!inviteCode) {
      setError("注册时需要填写邀请码");
      return;
    }

    if (!name || !email || !password) {
      setError("请完整填写注册信息");
      return;
    }

    startTransition(async () => {
      setIsPending(true);
      setError("");

      const result = await authClient.signUp.email({
        name,
        email,
        password,
      });

      setIsPending(false);

      if (result.error) {
        setError(result.error.message ?? "注册失败，请稍后重试");
        return;
      }

      router.replace(nextPath);
      router.refresh();
    });
  };

  return (
    <Card className="w-full max-w-md border-[rgba(57,130,152,0.16)] bg-white/96 shadow-[0_24px_60px_rgba(33,92,110,0.12)]">
      <CardHeader className="space-y-3">
        <div className="space-y-1">
          <CardTitle className="text-2xl text-[rgb(23,89,108)]">用户登录</CardTitle>
          <CardDescription className="text-sm text-slate-600">
            先接入最小用户体系，当前支持注册、登录和退出登录。
          </CardDescription>
        </div>
        <Tabs
          value={mode}
          onValueChange={(value) => {
            setMode(value as AuthMode);
            setError("");
          }}
        >
          <TabsList className="grid w-full grid-cols-2 bg-[rgb(233,244,246)]">
            <TabsTrigger
              value="login"
              className="data-[state=active]:border-[rgba(57,130,152,0.2)] data-[state=active]:bg-white data-[state=active]:text-[rgb(23,89,108)]"
            >
              登录
            </TabsTrigger>
            <TabsTrigger
              value="register"
              className="data-[state=active]:border-[rgba(57,130,152,0.2)] data-[state=active]:bg-white data-[state=active]:text-[rgb(23,89,108)]"
            >
              注册
            </TabsTrigger>
          </TabsList>

          <TabsContent value="login" className="hidden" />
          <TabsContent value="register" className="hidden" />
        </Tabs>
      </CardHeader>
      <CardContent className="space-y-4">
        {error ? (
          <Alert
            variant="destructive"
            className="border-red-200 bg-red-50 text-red-700"
          >
            <AlertCircleIcon className="size-4" />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}

        {mode === "login" ? (
          <div className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm text-slate-600">邮箱</label>
              <Input
                className={INPUT_CLASS_NAME}
                type="email"
                value={loginForm.email}
                placeholder="请输入邮箱"
                onChange={(event) =>
                  setLoginForm((current) => ({
                    ...current,
                    email: event.target.value,
                  }))
                }
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm text-slate-600">密码</label>
              <Input
                className={INPUT_CLASS_NAME}
                type="password"
                value={loginForm.password}
                placeholder="请输入密码"
                onChange={(event) =>
                  setLoginForm((current) => ({
                    ...current,
                    password: event.target.value,
                  }))
                }
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    handleLogin();
                  }
                }}
              />
            </div>
            <Button
              className={`w-full ${PRIMARY_BUTTON_CLASS_NAME}`}
              disabled={isPending}
              onClick={handleLogin}
            >
              {isPending ? "登录中..." : "登录"}
            </Button>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm text-slate-600">邀请码</label>
              <Input
                className={INPUT_CLASS_NAME}
                value={registerForm.inviteCode}
                placeholder="先填写即可，当前不校验"
                onChange={(event) =>
                  setRegisterForm((current) => ({
                    ...current,
                    inviteCode: event.target.value,
                  }))
                }
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm text-slate-600">昵称</label>
              <Input
                className={INPUT_CLASS_NAME}
                value={registerForm.name}
                placeholder="请输入昵称"
                onChange={(event) =>
                  setRegisterForm((current) => ({
                    ...current,
                    name: event.target.value,
                  }))
                }
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm text-slate-600">邮箱</label>
              <Input
                className={INPUT_CLASS_NAME}
                type="email"
                value={registerForm.email}
                placeholder="请输入邮箱"
                onChange={(event) =>
                  setRegisterForm((current) => ({
                    ...current,
                    email: event.target.value,
                  }))
                }
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm text-slate-600">密码</label>
              <Input
                className={INPUT_CLASS_NAME}
                type="password"
                value={registerForm.password}
                placeholder="密码至少 8 位"
                onChange={(event) =>
                  setRegisterForm((current) => ({
                    ...current,
                    password: event.target.value,
                  }))
                }
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    handleRegister();
                  }
                }}
              />
            </div>
            <Button
              className={`w-full ${PRIMARY_BUTTON_CLASS_NAME}`}
              disabled={isPending}
              onClick={handleRegister}
            >
              {isPending ? "注册中..." : "注册并进入工作区"}
            </Button>
          </div>
        )}

        <p className="text-center text-sm text-slate-500">
          返回首页请访问{" "}
          <Link
            href="/"
            className="text-[rgb(57,130,152)] underline underline-offset-4"
          >
            财政历史智能知识库
          </Link>
        </p>
      </CardContent>
    </Card>
  );
}
