import React from 'react'
import {
    Container,
    Box,
    Heading,
    Text,
    Button,
    VStack,
    useToast
} from '@chakra-ui/react'
import { ethers } from 'ethers'
import Link from 'next/link'

export default function Home() {
    const toast = useToast()

    const connectWallet = async () => {
        if (typeof window.ethereum !== 'undefined') {
            try {
                // درخواست اتصال به MetaMask
                await window.ethereum.request({ method: 'eth_requestAccounts' })

                // ایجاد provider
                const provider = new ethers.providers.Web3Provider(window.ethereum)

                toast({
                    title: 'Connected Successfully',
                    description: 'Your wallet has been connected.',
                    status: 'success',
                    duration: 5000,
                    isClosable: true,
                })
            } catch (error) {
                toast({
                    title: 'Connection Error',
                    description: 'Please make sure MetaMask is installed and unlocked.',
                    status: 'error',
                    duration: 5000,
                    isClosable: true,
                })
            }
        } else {
            toast({
                title: 'MetaMask Not Installed',
                description: 'Please install MetaMask first.',
                status: 'warning',
                duration: 5000,
                isClosable: true,
            })
        }
    }

    return (
        <Container maxW="container.lg" py={10}>
            <VStack spacing={8} align="stretch">
                <Box textAlign="center">
                    <Heading mb={4}>Uniswap Marketplace</Heading>
                    <Text fontSize="xl" mb={8}>
                        Connect your wallet to get started
                    </Text>

                    <VStack spacing={4}>
                        <Button colorScheme="blue" size="lg" onClick={connectWallet}>
                            Connect MetaMask
                        </Button>

                        <Link href="/Dashboard">
                            <Button variant="outline">
                                View Dashboard
                            </Button>
                        </Link>
                    </VStack>
                </Box>
            </VStack>
        </Container>
    )
} 