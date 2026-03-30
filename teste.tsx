import { View, Text, TouchableOpacity, Alert } from "react-native"
import containerStyle from "../../styles/global/containerStyle"
import { Feather } from "@expo/vector-icons"
import styles from "../../styles/profile/deleteProfileStyle"
import BackButton from "../../components/BackButton"
import CustomInput from "../../components/CustomInput"
import ButtonComponent from "../../components/buttons/ButtonComponent"
import ModalDelete from "../../components/modals/ModalDelete"
import { useState } from "react"
import { deleteUser, signInWithEmailAndPassword } from "firebase/auth"
import { auth } from "../../../firebaseConfig"
import { RouteProp, useRoute } from "@react-navigation/native"
import HeaderProfileComponent from "../../components/profile/HeaderProfileComponet"
import { doc, deleteDoc } from "firebase/firestore"; // <-- NOVO
import { auth, db } from "../../../firebaseConfig"; // <-- GARANTA QUE O db ESTÁ IMPORTADO

type DeleteProfileProps = {
    email: string
}

const DeleteProfileScreen: React.FC = ({navigation}: any) => {
    const [visible, setVisible] = useState(false);
    const route = useRoute<RouteProp<{params: DeleteProfileProps}, 'params'>>()
    const { email } = route.params
    const [password, setPassword] = useState('');

    const handleClickDelete = async (password: string) => {
        
        try{
            const userCredential = await signInWithEmailAndPassword(auth, email, password)
            const user = userCredential.user 

            onst userDocRef = doc(db, "users", user.uid)
            await deleteDoc(userDocRef)
            await deleteUser(user)

            await deleteAsync('user', { email: email })

            Alert.alert("Sucesso", "Sua conta e seus dados foram completamente excluídos.")

            navigation.reset({
                index: 0,
                routes: [{ name: 'Login' }], 
            })
            
        } catch (error: any) {
            if (error.code === 'auth/invalid-credential' || error.code === 'auth/wrong-password') {
                Alert.alert("Erro", "Senha incorreta. Tente novamente.");
            } else {
                Alert.alert("Erro", "Não foi possível excluir a conta. Tente novamente mais tarde.");
                console.error("Erro fatal ao excluir usuário:", error.message);
            }
        } finally {
            setVisible(false)
        }        
    }

    return (
        <View style={[containerStyle.container, {justifyContent: 'space-between'}]}>
            <View>
                <View style={styles.header}>
                    <Text style={styles.headerTitle}>Perfil</Text>
                    <HeaderProfileComponent
                        navigation={navigation}
                    />
                </View>
                <ModalDelete
                    visible={visible}
                    onClose={() => setVisible(false)}
                    onPressCancel={() => setVisible(false)}
                    onPressDelete={() => handleClickDelete(password)}
                />
                <View style={styles.containerButtonBack}>
                    <BackButton
                        onPress={() => navigation.goBack()}
                    />
                    <Text style={styles.textContainer}>Excluir conta</Text>
                </View>
                <CustomInput
                    title="Digite sua senha"
                    placeholder="Digite sua senha aqui"
                    secureText={true}
                    setText={(text) => setPassword(text)}
                />
            </View>
            <View style={styles.containerBotton}>
                <ButtonComponent
                    name="Excluir conta"
                    onPress={() => setVisible(true)}
                />
            </View>
        </View>
    )
}

export default DeleteProfileScreen;
