import { useMutation } from '@tanstack/react-query';
import { Link, useNavigate } from '@tanstack/react-router';
import { useRef, useState, type FormEvent } from 'react';
import { FormattedMessage } from 'react-intl';

import { describeError, type ErrorMessage } from '@/api/errors';
import { register } from '@/api/session';
import { AgreementBox } from '@/components/AgreementBox';
import { Field, PasswordField } from '@/components/Field';
import { ErrorNotice } from '@/components/Notice';
import { PageHeading, usePageTitle } from '@/components/PageHeading';
import { SubmitButton } from '@/components/SubmitButton';
import type { MessageId } from '@/i18n';
import { focusFirstInvalid } from '@/lib/focusFirstInvalid';
import { emailError, NAME_MAX, nameError, newPasswordError, PASSWORD_MAX } from '@/lib/validation';

import { pendingEmail } from './pendingEmail';

interface Errors {
  name?: MessageId | null;
  email?: MessageId | null;
  password?: MessageId | null;
  agreement?: MessageId | null;
}

export function RegisterPage() {
  const navigate = useNavigate();
  usePageTitle('register.title');

  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [agreed, setAgreed] = useState(false);
  const [errors, setErrors] = useState<Errors>({});
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const emailRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);
  const agreementRef = useRef<HTMLInputElement>(null);

  const request = useMutation({
    mutationFn: () => register(name.trim(), email.trim(), password),
    // The API answers the same way for every address, and so does this screen.
    onSuccess() {
      pendingEmail.set(email.trim());
      void navigate({ to: '/verify-email' });
    },
    onError(error) {
      setProblem(describeError(error));
    },
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (request.isPending) return;
    const found: Errors = {
      name: nameError(name),
      email: emailError(email),
      password: newPasswordError(password),
      agreement: agreed ? null : 'agreement.required',
    };
    setErrors(found);
    setProblem(null);
    const stopped = focusFirstInvalid(
      [found.name, nameRef],
      [found.email, emailRef],
      [found.password, passwordRef],
      [found.agreement, agreementRef],
    );
    if (!stopped) request.mutate();
  };

  return (
    <>
      <div className="l-stack l-stack--tight">
        <PageHeading>
          <FormattedMessage id="register.title" />
        </PageHeading>
        <p className="u-secondary">
          <FormattedMessage id="register.lead" />
        </p>
      </div>

      <ErrorNotice message={problem} />

      <form className="l-stack" noValidate onSubmit={onSubmit}>
        <Field
          id="register-name"
          ref={nameRef}
          label={<FormattedMessage id="register.name" />}
          autoComplete="name"
          maxLength={NAME_MAX}
          required
          value={name}
          onChange={setName}
          error={errors.name}
        />
        <Field
          id="register-email"
          ref={emailRef}
          label={<FormattedMessage id="common.email" />}
          type="email"
          autoComplete="username"
          dir="ltr"
          required
          value={email}
          onChange={setEmail}
          error={errors.email}
        />
        <PasswordField
          id="register-password"
          ref={passwordRef}
          label={<FormattedMessage id="common.password" />}
          autoComplete="new-password"
          maxLength={PASSWORD_MAX}
          required
          value={password}
          onChange={setPassword}
          error={errors.password}
          hint={<FormattedMessage id="register.passwordHint" />}
        />
        <AgreementBox
          id="register-terms"
          ref={agreementRef}
          checked={agreed}
          onChange={(checked) => {
            setAgreed(checked);
            if (checked) setErrors((current) => ({ ...current, agreement: null }));
          }}
          error={errors.agreement}
        />
        <SubmitButton busy={request.isPending}>
          <FormattedMessage id="register.submit" />
        </SubmitButton>
      </form>

      <p className="u-secondary">
        <FormattedMessage id="register.have" />{' '}
        <Link to="/sign-in">
          <FormattedMessage id="register.signIn" />
        </Link>
      </p>
    </>
  );
}
