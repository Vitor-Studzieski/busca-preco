# ADR 0002 · Sessões persistentes

O comprador pode manter a sessão neste dispositivo por 30 dias de inatividade, com renovação por uso. O prazo é provisório até o negócio definir a política final. Sem a opção, o cookie expira ao encerrar o navegador. O gerenciador de senhas pode preencher o formulário com os atributos padrão do Django.

O navegador recebe apenas o identificador de sessão via cookie HttpOnly, SameSite Lax e Secure sobre HTTPS em produção. As credenciais usam Argon2 como algoritmo preferido. A aplicação guarda a sessão no banco e oferece revogação de dispositivos. A troca de senha invalida sessões anteriores, incluindo sessões anteriores à lista de dispositivos. A revogação de outro dispositivo exige confirmação de senha.
