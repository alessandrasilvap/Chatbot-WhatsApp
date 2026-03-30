import { Feather } from "@expo/vector-icons";
import { View, Text, TouchableOpacity, ScrollView, ActivityIndicator } from "react-native"
import styles from "../../styles/profile/profileOptionsStyle";
import containerStyle from "../../styles/global/containerStyle";
import { useEffect, useState } from "react";
import ButtonProfileComponent from "../../components/buttonProfile/buttonProfileComponent";
import ButtonDarkComponent from "../../components/buttonProfile/buttonDarkModo";
import { selectAsync } from "../../database/repository/function";
import { getUserData, logout } from "../../firebase/loginAuth/loginFunctions";
import { getUserAuth } from "../../firebase/user/getUserAuth";
import { getPropsUserAuth } from "../../firebase/user/getPropsUserAuth";
import { isLoading } from "expo-font";
import colors from "../../styles/global/colorStyle";
import ModalDelete from "../../components/modals/ModalDelete";
import ModalLogout from "../../components/modals/ModalLogout";
import HeaderProfileComponent from "../../components/profile/HeaderProfileComponet";
import { deleteAsync } from '../../database/repository/function';


const ProfileOptionsScreen: React.FC = ({navigation}: any) => {
    const [userName, setUserName] = useState('');
    const [userEmail, setUserEmail] = useState('');
    const [userPhone, setUserPhone] = useState('')
    const [isLoading, setIsLoading] = useState(true)
    const [visible, setVisible] = useState(false);

    useEffect(() => {
        const getUser = async () => {
            const userData = await getUserData()
            const userAuth = await getUserAuth()
            const userProps = await getPropsUserAuth(userAuth.uid)

            if(userProps && userPhone === '') {
                setUserName(userProps.name)
                setUserEmail(userProps.email)
                setUserPhone(userProps.phone)
            }
        }

        getUser()
        if(userPhone !== ''){
            setIsLoading(false)
        }
    }, [userPhone])

    const handleSingOut = async () => {
        try {
            await logout(emailDoUsuarioAtual)

            navigation.reset({
                index: 0,
                routes: [{ name: 'Login' }],
            })
        } catch {
            console.error("Erro crítico ao sair da conta:", error)
        } finally {
            setVisible(false)
        }
    }

    const formatPhone = (value: string) => {
        if (!value) return "";

        let numbers = value.replace(/\D/g, "");

        //Remove código do país 55 se existir
        if (numbers.startsWith("55") && numbers.length > 11) {
            numbers = numbers.slice(2);
        }

        if (numbers.length === 11) {
            return numbers.replace(/(\d{2})(\d{5})(\d{4})/, "($1) $2-$3");
        }

        if (numbers.length === 10) {
            return numbers.replace(/(\d{2})(\d{4})(\d{4})/, "($1) $2-$3");
        }

        return numbers;
    };


   if (isLoading) {
        return (
            <View style={[containerStyle.container, { justifyContent: 'center', alignItems: 'center' }]}>
                <ActivityIndicator size="large" color={colors.blueDark} />
            </View>
        );
    }
    return (
        <View style={containerStyle.container}>
            <View style={styles.header}>
                <Text style={styles.headerTitle}>Perfil</Text>
                <HeaderProfileComponent
                    navigation={navigation}
                />
            </View>
            <ModalLogout
                visible={visible}
                onClose={() => setVisible(false)}
                onPressDelete={handleSingOut}
            />
            <View style={styles.containerBody}>
                <ScrollView>
                    <View style={styles.containerUserName}>
                        <Text style={styles.textUserName}>{userName}</Text>
                    </View>
                    <View style={styles.containerInfoUser}>
                        <ButtonProfileComponent
                            title={userEmail}
                            icon="mail"
                            onPress={() => navigation.navigate("EmailProfile", {email: userEmail})}
                        />
                        <ButtonProfileComponent
                            title={userPhone ? formatPhone(userPhone) : 'Adicionar telefone'}
                            icon="phone"
                            onPress={() => navigation.navigate("PhoneProfile", {phone: userPhone})}
                        />
                        <ButtonProfileComponent
                            title="Senha"
                            icon="lock"
                            onPress={() => navigation.navigate("PasswordProfile")}
                        />
                        <ButtonProfileComponent
                            title='Histórico de investimentos'
                            icon='clock'
                            onPress={() => navigation.nagivate("HistoryTransaction")}
                        />
                        <ButtonProfileComponent
                            title='Sair'
                            icon="log-out"
                            onPress={() => setVisible(true)}
                        />
                    </View>
                    <View style={styles.containerTextConfiguration}>
                        <Text style={styles.textConfiguration}>Configurações</Text>
                    </View>
                    <View style={styles.containerConfiguration}>
                        <ButtonDarkComponent
                            title="Modo escuro"
                            icon="moon"
                        />
                         <ButtonProfileComponent
                            title="Premium"
                            icon="star"
                            onPress={() => navigation.navigate("SubscriptionPremium")}
                        />
                        <ButtonProfileComponent
                            title="Notificações"
                            icon="bell"
                            onPress={() => navigation.navigate("NotificationProfile")}
                        />
                        <ButtonProfileComponent
                            title="Politíca de privacidade"
                            icon="alert-triangle"
                            onPress={() => navigation.navigate("PrivacyPolicy")}
                        />
                        <ButtonProfileComponent
                            title="Excuir conta"
                            icon="trash"
                            onPress={() => navigation.navigate("DeleteProfile", {email: userEmail})}
                        />
                    </View>
                </ScrollView>
            </View>
        </View>
    )
}

export default ProfileOptionsScreen;
