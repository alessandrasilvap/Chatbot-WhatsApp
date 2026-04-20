# ESTE ARQUIVO NÃO VAI PARA A NUVEM, É APENAS UM GERADOR DE SENHA
from werkzeug.security import generate_password_hash

senha_que_o_atendente_quer = ""
hash_gerado = generate_password_hash(senha_que_o_atendente_quer)

# Ao rodar, o terminal cuspirá um texto logo
    # Ex: scrypt:32768:8:1$KxY...$9b2...
print(f"Copie este hash e cole no banco de dados:")
print(hash_gerado)


# No MySql ao criar um login novo deve adicionar assim:
    # INSERT INTO atendentes (usuario, senha) 
        # VALUES ('admin', 'scrypt:32768:8:1$KxY...$9b2...');
# Já o usuário apenas dgita '123' no campo senha

# senha: scrypt:32768:8:1$ayOlInQpFUBSEvqi$9efdf0fdfb14b412d1f4c21f9771626ff4aeb76624edcd8c79397ccea1d71fa9d98f1d9913c335cfe944bbfcdbdecdc93b7621857ca8fb99d5c119cae1745754
