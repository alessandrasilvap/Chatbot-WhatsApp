// src/firebase/loginAuth/loginFunctions.ts

import * as SecureStore from 'expo-secure-store';
import { signOut } from 'firebase/auth';
import { auth } from '../../../firebaseConfig';
import { deleteAsync } from '../../database/repository/function';

export async function saveUserData(user: { uid: string; email: string; password?: string}) {
  await SecureStore.setItemAsync('userData', JSON.stringify(user));
}

export async function getUserData() {
  const stored = await SecureStore.getItemAsync('userData');
  return stored ? JSON.parse(stored) : null;
}

export async function logout(userEmail?: string) {
  try {
    console.log("Iniciando processo de logout completo...");

    // 1. Extermina os dados do SecureStore
    await SecureStore.deleteItemAsync('userData');

    // 2. Desloga oficialmente do Firebase Auth
    await signOut(auth);

    // 3. Extermina os dados locais do SQLite (LGPD e Segurança)
    // Se você tiver o email, deleta o específico. Se não, idealmente você deveria ter 
    // uma função para limpar a tabela inteira, mas vamos usar o que temos.
    if (userEmail) {
       await deleteAsync('user', { email: userEmail });
    }

    console.log("Logout concluído com sucesso.");
  } catch (error) {
    console.error("Erro crítico durante o processo de logout:", error);
    throw error; // Repassa o erro para a tela tratar (exibir um Alert)
  }
}
