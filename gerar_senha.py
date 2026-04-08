# ESTE ARQUIVO NÃO VAI PARA A NUVEM, É APENAS UM GERADOR DE SENHA
from werkzeug.security import generate_password_hash

senha_que_o_atendente_quer = "123"
hash_gerado = generate_password_hash(senha_que_o_atendente_quer)

# Ao rodar, o terminal cuspirá um texto logo
    # Ex: scrypt:32768:8:1$KxY...$9b2...
print(f"Copie este hash e cole no banco de dados:")
print(hash_gerado)


# No MySql ao criar um login novo deve adicionar assim:
    # INSERT INTO atendentes (usuario, senha) 
        # VALUES ('admin', 'scrypt:32768:8:1$KxY...$9b2...');
# Já o usuário apenas dgita '123' no campo senha