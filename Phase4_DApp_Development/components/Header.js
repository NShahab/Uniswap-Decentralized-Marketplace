//اضافه کردن Header.js برای هدایت بین صفحات
import React from 'react'
import {
    Box,
    Flex,
    Button,
    Text,
    HStack,
    useToast
} from '@chakra-ui/react'
import { useAccount, useConnect, useDisconnect } from 'wagmi'
import { MetaMaskConnector } from 'wagmi/connectors/metaMask'
import Link from 'next/link'

export default function Header() {
    const { address, isConnected } = useAccount()
    const { connect } = useConnect({
        connector: new MetaMaskConnector()
    })
    const { disconnect } = useDisconnect()
    const toast = useToast()

    const handleConnect = async () => {
        try {
            await connect()
        } catch (error) {
            toast({
                title: 'خطا در اتصال',
                description: 'لطفاً از نصب و باز بودن MetaMask اطمینان حاصل کنید.',
                status: 'error',
                duration: 5000,
                isClosable: true,
            })
        }
    }

    return (
        <Box py={4} px={8} borderBottom="1px" borderColor="gray.200" bg="white">
            <Flex justify="space-between" align="center">
                <HStack spacing={8}>
                    <Link href="/" passHref>
                        <Text fontSize="xl" fontWeight="bold" cursor="pointer">
                            یونی‌سواپ مارکت
                        </Text>
                    </Link>
                    <Link href="/marketplace" passHref>
                        <Text cursor="pointer">مارکت‌پلیس</Text>
                    </Link>
                    <Link href="/swap" passHref>
                        <Text cursor="pointer">سوآپ توکن</Text>
                    </Link>
                    {isConnected && (
                        <Link href="/profile" passHref>
                            <Text cursor="pointer">پروفایل</Text>
                        </Link>
                    )}
                </HStack>

                {!isConnected ? (
                    <Button colorScheme="blue" onClick={handleConnect}>
                        اتصال به MetaMask
                    </Button>
                ) : (
                    <HStack>
                        <Text fontSize="sm" color="gray.500">
                            {address?.slice(0, 6)}...{address?.slice(-4)}
                        </Text>
                        <Button size="sm" colorScheme="red" onClick={() => disconnect()}>
                            قطع اتصال
                        </Button>
                    </HStack>
                )}
            </Flex>
        </Box>
    )
}
